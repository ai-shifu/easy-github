#!/usr/bin/env python3
"""Local coordination prototype; identities and handoff are declarations, not locks.

External AI tools edit detached workspaces. This program never updates main.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


class PrototypeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Prototype:
    TEAM_REF = "refs/heads/prototype-team"

    def __init__(self, state: Path):
        self.state = Path(state).resolve()
        self.repo = self.state / "repo.git"

    @staticmethod
    def _require(condition, code, message):
        if not condition:
            raise PrototypeError(code, message)

    @staticmethod
    def _id(prefix):
        return prefix + "-" + uuid.uuid4().hex[:16]

    @staticmethod
    def _text(value, label):
        value = str(value).strip()
        Prototype._require(bool(value), "invalid_input", label + " is required")
        return value

    def _git(self, *args, cwd=None, env=None, input=None):
        command = ["git"]
        command += ["-C", str(cwd)] if cwd else ["--git-dir", str(self.repo)]
        result = subprocess.run(command + list(args), input=input, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={**os.environ, **(env or {})})
        if result.returncode:
            raise PrototypeError("git_error", result.stderr.strip() or result.stdout.strip())
        return result.stdout.rstrip("\n")

    @contextmanager
    def _locked(self, initializing=False):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if initializing:
                    yield None
                else:
                    path = self.state / "state.json"
                    self._require(path.is_file(), "not_initialized", "State is not initialized")
                    data = json.loads(path.read_text())
                    self._recover_acceptance(data)
                    yield data
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _save(self, data, path=None):
        path = path or self.state / "state.json"
        descriptor, name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _acceptance_intent(review, delivery):
        return {"review_id": review["id"], "delivery_id": delivery["id"],
                "work_id": review["work_id"], "revision": review["revision"],
                "attempt": delivery["attempt"], "reviewer": review["reviewer"],
                "old_sha": review["team_sha"], "candidate_sha": review["candidate_sha"]}

    def _recover_acceptance(self, data):
        """Reconcile an interrupted, already-authorized acceptance under the lock."""
        intent = data.get("pending_accept")
        if intent is None:
            return
        review = data.get("reviews", {}).get(intent.get("review_id")) if isinstance(intent, dict) else None
        delivery = data.get("deliveries", {}).get(review.get("delivery_id")) if review else None
        work = data.get("works", {}).get(review.get("work_id")) if review else None
        checks = list(review.get("checks", {}).values()) if review else []
        valid = (review and delivery and work
                 and intent == self._acceptance_intent(review, delivery)
                 and review.get("status") == "ready" and not review.get("preview_only")
                 and review["reviewer"] != delivery["owner"]
                 and work["latest_delivery"] == delivery["id"]
                 and work["revision"] == delivery["revision"] == review["revision"]
                 and work["attempt"] == delivery["attempt"]
                 and checks and all(check.get("status") == "passed"
                                    and check.get("snapshot_sha") == review["candidate_sha"]
                                    for check in checks))
        self._require(valid, "acceptance_conflict",
                      "Pending acceptance no longer matches its review; state was not changed")
        actual = self._team()
        self._require(actual in (intent["old_sha"], intent["candidate_sha"]), "acceptance_conflict",
                      "Team ref differs from both pending acceptance versions; state was not changed")
        if actual == intent["candidate_sha"]:
            review["accepted"] = True
        else:
            self._require(not review.get("accepted"), "acceptance_conflict",
                          "Accepted review conflicts with the old team ref; state was not changed")
            # The ref transition never took effect. Drop only the unapplied
            # intent; an explicit retry must pass all normal acceptance checks.
        data.pop("pending_accept")
        self._save(data)

    @staticmethod
    def _accepted_result(review):
        return {"status": "accepted", "review_id": review["id"],
                "delivery_id": review["delivery_id"], "work_id": review["work_id"],
                "team_sha": review["candidate_sha"], "candidate_sha": review["candidate_sha"]}

    @classmethod
    def initialize(cls, source: Path, state: Path) -> "Prototype":
        prototype = cls(state)
        source = Path(source).resolve()
        cls._require(source.is_dir(), "invalid_source", "Source must be a local Git directory")
        cls._require(source != prototype.state and source not in prototype.state.parents,
                     "invalid_state", "State must be outside the source repository")
        with prototype._locked(initializing=True):
            cls._require(not (prototype.state / "state.json").exists()
                         and not prototype.repo.exists(), "already_initialized",
                         "State already contains a prototype or repository")
            head = prototype._git("rev-parse", "--verify", "HEAD^{commit}", cwd=source)
            prototype._git("init", "--bare", str(prototype.repo), cwd=prototype.state)
            prototype._git("symbolic-ref", "HEAD", cls.TEAM_REF)
            prototype._git("config", "user.name", "Newgit Prototype")
            prototype._git("config", "user.email", "prototype@localhost")
            prototype._git("fetch", "--no-tags", "--no-write-fetch-head", str(source),
                           head + ":" + cls.TEAM_REF)
            prototype._require(prototype._team() == head, "verification_failed",
                               "Initial team ref does not match the source snapshot")
            prototype._save({"version": 1, "source": str(source), "source_head": head,
                             "works": {}, "deliveries": {}, "reviews": {}})
        return prototype

    def _team(self):
        return self._git("rev-parse", "--verify", self.TEAM_REF + "^{commit}")

    def _get(self, data, collection, identifier):
        self._require(identifier in data[collection], "not_found",
                      "Unknown " + collection.rstrip("s") + ": " + str(identifier))
        return data[collection][identifier]

    def _dependency(self, data, work_id, onto_delivery_id):
        if onto_delivery_id is None:
            return None
        dependency = self._get(data, "deliveries", onto_delivery_id)
        current, seen = dependency, {work_id}
        while current:
            self._require(current["work_id"] not in seen, "invalid_dependency",
                          "A preview cannot depend on its own work or a dependency cycle")
            seen.add(current["work_id"])
            other = self._get(data, "works", current["work_id"])
            self._require(other["latest_delivery"] == current["id"], "superseded_dependency",
                          "A preview dependency has a newer delivery; explicitly choose a current dependency")
            parent = current.get("onto_delivery_id")
            current = self._get(data, "deliveries", parent) if parent else None
        return dependency

    def _new_attempt(self, work, base, onto_delivery_id=None):
        number = work["attempt"] + 1
        workspace = self.state / "workspaces" / (work["id"] + "-a" + str(number))
        workspace.parent.mkdir(exist_ok=True)
        self._git("worktree", "add", "--detach", str(workspace), base)
        attempt = {"attempt": number, "workspace": str(workspace), "base": base}
        if onto_delivery_id is not None:
            attempt.update(onto_delivery_id=onto_delivery_id, preview_only=True)
        work["attempts"].append(attempt)
        work.pop("onto_delivery_id", None)
        work.pop("preview_only", None)
        work.update(attempt)
        return {"id": work["id"], **attempt}

    def start(self, owner, tool, title):
        owner, tool, title = [self._text(value, label) for value, label in
                              ((owner, "owner"), (tool, "tool"), (title, "title"))]
        with self._locked() as data:
            work = {"id": self._id("w"), "owner": owner, "tool": tool, "title": title,
                    "attempt": 0, "revision": 0, "attempts": [], "latest_delivery": None}
            result = self._new_attempt(work, self._team())
            data["works"][work["id"]] = work
            self._save(data)
            return result

    @contextmanager
    def _index(self):
        with tempfile.TemporaryDirectory(prefix="index-", dir=self.state) as directory:
            yield {"GIT_INDEX_FILE": str(Path(directory) / "index")}

    def _commit(self, tree, parents, message):
        args = ["commit-tree", tree]
        for parent in parents:
            args.extend(["-p", parent])
        return self._git(*args, input=message + "\n")

    def _keep(self, ref, sha):
        # An empty old value requires that this immutable snapshot ref is new.
        self._git("update-ref", ref, sha, "")

    def submit(self, work_id, attempt, summary="", handoff=False):
        self._require(handoff is True, "handoff_required",
                      "Declare handoff after stopping the external writer; this does not lock it")
        with self._locked() as data:
            work = self._get(data, "works", work_id)
            self._require(str(attempt) == str(work["attempt"]), "stale_attempt",
                          "This attempt was replaced; use the latest workspace")
            dependency = self._dependency(data, work_id, work.get("onto_delivery_id"))
            workspace = Path(work["workspace"])
            common = self._git("rev-parse", "--path-format=absolute", "--git-common-dir",
                               cwd=workspace)
            self._require(Path(common).resolve() == self.repo, "invalid_workspace",
                          "Workspace no longer belongs to this prototype")
            original_head = self._git("rev-parse", "HEAD", cwd=workspace)
            with self._index() as env:
                # Seed from actual HEAD so externally committed, ignored files stay tracked.
                self._git("read-tree", original_head, cwd=workspace, env=env)
                self._git("add", "-A", "--", ".", cwd=workspace, env=env)
                tree = self._git("write-tree", cwd=workspace, env=env)
            revision = work["revision"] + 1
            sha = self._commit(tree, [work["base"]],
                               "Delivery " + work_id + " revision " + str(revision) + "\n\n" + str(summary))
            delivery = {"id": self._id("d"), "work_id": work_id, "revision": revision,
                        "sha": sha, "base": work["base"], "attempt": work["attempt"],
                        "owner": work["owner"], "summary": str(summary), "workspace_head": original_head}
            if dependency:
                delivery.update(onto_delivery_id=dependency["id"], preview_only=True)
            self._keep("refs/prototype/deliveries/" + delivery["id"], sha)
            data["deliveries"][delivery["id"]] = delivery
            work.update(revision=revision, latest_delivery=delivery["id"])
            self._save(data)
            return delivery

    def _paths(self, base, sha):
        output = self._git("diff", "--name-only", "--no-renames", "-z", base, sha, "--")
        return set(output.split("\0")) - {""}

    def _diff(self, base, sha):
        return self._git("diff", "--no-ext-diff", "--no-textconv", "--binary", base, sha, "--")

    def review(self, delivery_id, reviewer, onto_delivery_id=None):
        reviewer = self._text(reviewer, "reviewer")
        with self._locked() as data:
            delivery = self._get(data, "deliveries", delivery_id)
            self._require(reviewer != delivery["owner"], "self_review", "Authors cannot review their own delivery")
            team = self._team()
            onto_delivery_id = onto_delivery_id or delivery.get("onto_delivery_id")
            dependency = self._dependency(data, delivery["work_id"], onto_delivery_id)
            comparison = dependency["sha"] if dependency else team
            overlap = sorted(self._paths(delivery["base"], comparison)
                             & self._paths(delivery["base"], delivery["sha"]))
            result = {"id": self._id("r"), "delivery_id": delivery_id,
                      "work_id": delivery["work_id"], "revision": delivery["revision"],
                      "reviewer": reviewer, "team_sha": team, "candidate_sha": None,
                      "status": "needs_update", "overlapping_paths": overlap, "checks": {},
                      "diff": self._diff(delivery["base"], delivery["sha"]),
                      "team_diff": self._diff(delivery["base"], team)}
            if dependency:
                result.update(preview_only=True, onto_delivery_id=dependency["id"],
                              comparison_sha=comparison,
                              comparison_diff=self._diff(delivery["base"], comparison))
            if not overlap:
                candidate = delivery["sha"]
                if comparison != delivery["base"]:
                    try:
                        with self._index() as env:
                            self._git("read-tree", "-i", "-m", delivery["base"], comparison, delivery["sha"], env=env)
                            tree = self._git("write-tree", env=env)
                        candidate = self._commit(tree, [comparison, delivery["sha"]], "Candidate " + result["id"])
                    except PrototypeError as error:
                        if error.code != "git_error":
                            raise
                        result["reason"] = "Git could not combine these snapshots: " + str(error)
                        candidate = None
                if candidate:
                    self._keep("refs/prototype/reviews/" + result["id"], candidate)
                    result.update(status="ready", candidate_sha=candidate,
                                  diff=self._diff(comparison, candidate))
            if overlap:
                result["reason"] = "Both sides changed these files; external revision is required"
            data["reviews"][result["id"]] = result
            self._save(data)
            return result

    def record_check(self, review_id, snapshot_sha, name, status, detail=""):
        name = self._text(name, "check name")
        self._require(status in ("passed", "failed"), "invalid_input", "Check status must be passed or failed")
        with self._locked() as data:
            review = self._get(data, "reviews", review_id)
            self._dependency(data, review["work_id"], review.get("onto_delivery_id"))
            self._require(review["status"] == "ready", "needs_update", "Review has no combinable candidate")
            self._require(not review.get("accepted"), "already_accepted", "Review was already accepted")
            self._require(snapshot_sha == review["candidate_sha"], "wrong_snapshot",
                          "Checks must name the exact candidate SHA")
            check = {"review_id": review_id, "snapshot_sha": snapshot_sha,
                     "name": name, "status": status, "detail": str(detail)}
            review["checks"][name] = check
            self._save(data)
            return check

    def accept(self, review_id, reviewer):
        reviewer = self._text(reviewer, "reviewer")
        with self._locked() as data:
            review = self._get(data, "reviews", review_id)
            self._require(not review.get("preview_only"), "preview_only",
                          "Preview-only reviews cannot update the team version")
            delivery = self._get(data, "deliveries", review["delivery_id"])
            work = self._get(data, "works", delivery["work_id"])
            self._require(reviewer != delivery["owner"], "self_review", "Authors cannot accept their own delivery")
            self._require(reviewer == review["reviewer"], "wrong_reviewer", "Only this review's reviewer may accept it")
            if review.get("accepted") and self._team() == review["candidate_sha"]:
                # A crash after durable completion can lose the response. A
                # matching retry reports that completion without another write.
                return self._accepted_result(review)
            self._require(not review.get("accepted"), "already_accepted", "Review was already accepted")
            self._require(review["status"] == "ready", "needs_update", "Delivery requires an external update")
            self._require(work["latest_delivery"] == delivery["id"]
                          and work["revision"] == delivery["revision"], "superseded_delivery",
                          "A newer delivery superseded this one")
            self._require(delivery["attempt"] == work["attempt"], "stale_attempt",
                          "An update is in progress; submit and review the new attempt")
            checks = list(review["checks"].values())
            self._require(bool(checks), "checks_required", "At least one candidate check is required")
            self._require(all(item["status"] == "passed" for item in checks),
                          "checks_failed", "Every recorded candidate check must pass")
            self._require(self._team() == review["team_sha"], "stale_review",
                          "The team version changed; review the delivery again")
            # Journal authorization and the exact CAS before changing Git. If
            # either store cannot finish, the next locked call reconciles them.
            data["pending_accept"] = self._acceptance_intent(review, delivery)
            self._save(data)
            try:
                self._git("update-ref", self.TEAM_REF, review["candidate_sha"], review["team_sha"])
            except PrototypeError as error:
                if self._team() != review["team_sha"]:
                    raise PrototypeError("stale_review", "Team changed during compare-and-swap") from error
                raise
            actual = self._team()
            self._require(actual == review["candidate_sha"], "verification_failed",
                          "Team ref readback did not match the accepted candidate")
            review["accepted"] = True
            data.pop("pending_accept")
            self._save(data)
            return self._accepted_result(review)

    def prepare_update(self, delivery_id, onto_delivery_id=None):
        with self._locked() as data:
            delivery = self._get(data, "deliveries", delivery_id)
            work = self._get(data, "works", delivery["work_id"])
            self._require(work["latest_delivery"] == delivery_id, "superseded_delivery",
                          "Update the latest delivery, not a superseded revision")
            team = self._team()
            onto_delivery_id = onto_delivery_id or delivery.get("onto_delivery_id")
            dependency = self._dependency(data, work["id"], onto_delivery_id)
            comparison = dependency["sha"] if dependency else team
            result = self._new_attempt(work, comparison, onto_delivery_id)
            directory = self.state / "context"
            directory.mkdir(exist_ok=True)
            path = directory / (work["id"] + "-a" + str(work["attempt"]) + ".json")
            context = {"work_id": work["id"], "attempt": work["attempt"],
                       "instruction": "External AI must rebuild the intended change on this new base. Original workspace is retained.",
                       "original_base_sha": delivery["base"], "delivery_sha": delivery["sha"],
                       "latest_team_sha": team, "summary": delivery["summary"],
                       "delivery_diff": self._diff(delivery["base"], delivery["sha"]),
                       "team_diff": self._diff(delivery["base"], team)}
            if dependency:
                context.update(preview_only=True, onto_delivery_id=dependency["id"],
                               comparison_sha=comparison,
                               comparison_diff=self._diff(delivery["base"], comparison))
                result.update(team_sha=team, comparison_sha=comparison)
            self._save(context, path)
            result["context_file"] = str(path)
            work["attempts"][-1]["context_file"] = str(path)
            self._save(data)
            return result

    def status(self):
        with self._locked() as data:
            return {"team_sha": self._team(), "team_ref": self.TEAM_REF, "repo": str(self.repo),
                    "workings": list(data["works"].values()),
                    "deliveries": list(data["deliveries"].values()),
                    "reviews": list(data["reviews"].values())}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise PrototypeError("invalid_arguments", message)


def main():
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("--source", type=Path, required=True)
    start = commands.add_parser("start")
    for option in ("owner", "tool", "title"):
        start.add_argument("--" + option, required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--work", required=True)
    submit.add_argument("--attempt", type=int, required=True)
    submit.add_argument("--handoff", action="store_true")
    submit.add_argument("--summary", default="")
    review = commands.add_parser("review")
    review.add_argument("--delivery", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--onto-delivery")
    check = commands.add_parser("check")
    for option in ("review", "snapshot", "name", "status"):
        check.add_argument("--" + option, required=True)
    check.add_argument("--detail", default="")
    accept = commands.add_parser("accept")
    accept.add_argument("--review", required=True)
    accept.add_argument("--reviewer", required=True)
    update = commands.add_parser("update")
    update.add_argument("--delivery", required=True)
    update.add_argument("--onto-delivery")
    commands.add_parser("status")
    try:
        args = parser.parse_args()
        prototype = Prototype(args.state)
        if args.command == "init":
            result = Prototype.initialize(args.source, args.state).status()
        elif args.command == "start":
            result = prototype.start(args.owner, args.tool, args.title)
        elif args.command == "submit":
            result = prototype.submit(args.work, args.attempt, args.summary, args.handoff)
        elif args.command == "review":
            result = prototype.review(args.delivery, args.reviewer, args.onto_delivery)
        elif args.command == "check":
            result = prototype.record_check(args.review, args.snapshot, args.name, args.status, args.detail)
        elif args.command == "accept":
            result = prototype.accept(args.review, args.reviewer)
        elif args.command == "update":
            result = prototype.prepare_update(args.delivery, args.onto_delivery)
        else:
            result = prototype.status()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (PrototypeError, OSError, ValueError) as error:
        print(json.dumps({"error": {"code": getattr(error, "code", "internal_error"),
                                    "message": str(error)}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
