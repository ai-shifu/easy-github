"""Publish frozen test deliveries and COMMENT reviews through the authenticated gh CLI.

This adapter has no merge or approval operation. It is intentionally limited to
private repositories named newgit-integration-* on github.com.
"""

import argparse
import json
import re
import subprocess
import time
import uuid
from pathlib import Path


class GitHubAdapterError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class GitHubReviewAdapter:
    def __init__(self, repository, git_dir: Path, evidence_dir: Path, *, runner=None):
        self._require(isinstance(repository, str)
                      and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository),
                      "invalid_repository", "Expected an explicit owner/repository")
        self._require(all(part not in {".", ".."} for part in repository.split("/")),
                      "invalid_repository", "Repository identifiers cannot contain dot segments")
        name = repository.split("/", 1)[1]
        self._require(name.startswith("newgit-integration-")
                      and len(name) > len("newgit-integration-"),
                      "not_test_repository", "Only newgit-integration-* repositories are allowed")
        self.repository = repository
        self.git_dir = Path(git_dir).resolve()
        self.evidence_dir = Path(evidence_dir).resolve()
        self._require(self.git_dir.is_dir(), "invalid_git_directory", "Git directory must exist")
        self.runner = runner or subprocess.run
        self.evidence_paths = []

    @staticmethod
    def _require(condition, code, message):
        if not condition:
            raise GitHubAdapterError(code, message)

    @staticmethod
    def _sha(value):
        GitHubReviewAdapter._require(isinstance(value, str)
                                    and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value),
                                    "invalid_sha", "Expected a full lowercase commit SHA")
        return value

    @staticmethod
    def _number(value):
        GitHubReviewAdapter._require(type(value) is int and value > 0,
                                    "invalid_number", "Expected a positive pull request number")
        return value

    @staticmethod
    def _branch(value):
        # Only the experiment's shared base or its delivery branches are targets.
        GitHubReviewAdapter._require(value == "prototype-team" or
                                    (isinstance(value, str)
                                     and re.fullmatch(r"newgit/[A-Za-z0-9_-]+", value)),
                                    "invalid_branch", "Expected prototype-team or a newgit/<work_id> branch")
        return value

    @staticmethod
    def _redact(value):
        if isinstance(value, dict):
            return {key: ("[redacted]" if re.search(
                r"(^|_)(token|password|authorization|secret)($|_)", key, re.I)
                else GitHubReviewAdapter._redact(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [GitHubReviewAdapter._redact(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b",
                          "[redacted]", value)
        return value

    def _evidence(self, kind, data):
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"{time.time_ns()}-{uuid.uuid4().hex[:8]}-{kind}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self._redact(data), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        self.evidence_paths.append(str(path))

    def _run(self, args, *, input_text=None):
        try:
            return self.runner(args, cwd=self.git_dir, input=input_text, text=True,
                               capture_output=True, shell=False, check=False)
        except OSError as error:
            raise GitHubAdapterError("execution_failed", f"Could not execute {args[0]}") from error

    def _api(self, method, path, payload=None, *, allow_not_found=False):
        self._require(method in {"GET", "POST", "PATCH"}, "unsupported_method", "Unsupported API method")
        prefix = f"/repos/{self.repository}"
        self._require(isinstance(path, str)
                      and (path == "/user" or path == prefix or path.startswith(prefix + "/"))
                      and all(part not in {".", ".."} for part in path.split("/")),
                      "unexpected_endpoint", "API request escaped the selected repository")
        args = ["gh", "api", "--hostname", "github.com", "--method", method, path]
        if payload is not None:
            args.extend(["--input", "-"])
        result = self._run(args, input_text=(json.dumps(payload, ensure_ascii=False)
                                             if payload is not None else None))
        try:
            response = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            self._evidence("api-error", {"method": method, "path": path,
                                         "exit_code": result.returncode, "response_format": "not_json"})
            raise GitHubAdapterError("invalid_api_response", f"{method} {path} did not return JSON")
        self._evidence("api", {"method": method, "path": path,
                               "exit_code": result.returncode, "response": response})
        if result.returncode:
            not_found = (isinstance(response, dict) and str(response.get("status")) == "404")
            if allow_not_found and method == "GET" and not_found:
                return None
            raise GitHubAdapterError("github_request_failed",
                                     f"{method} {path} failed; inspect recorded response; no write was retried")
        self._require(isinstance(response, dict), "invalid_api_response", "Expected a GitHub JSON object")
        return response

    def _context(self):
        repo = self._api("GET", f"/repos/{self.repository}")
        self._require(repo.get("full_name", "").lower() == self.repository.lower(),
                      "wrong_repository", "GitHub returned a different repository")
        self._require(repo.get("private") is True, "not_private", "The test repository must be private")
        self._require(not repo.get("archived") and not repo.get("disabled"),
                      "repository_unavailable", "The test repository is archived or disabled")
        user = self._api("GET", "/user")
        self._require(isinstance(user.get("login"), str) and bool(user["login"].strip()),
                      "missing_identity", "GitHub did not identify the authenticated account")
        return user["login"]

    def _ref(self, branch, *, optional=False):
        return self._api("GET", f"/repos/{self.repository}/git/ref/heads/{branch}",
                         allow_not_found=optional)

    def _ref_sha(self, response, branch):
        self._require(response.get("ref") == f"refs/heads/{branch}"
                      and response.get("object", {}).get("type") == "commit",
                      "wrong_ref", "GitHub returned an unexpected branch reference")
        return self._sha(response["object"].get("sha"))

    def _pr(self, number):
        return self._api("GET", f"/repos/{self.repository}/pulls/{number}")

    def _verify_pr(self, pr, number, branch, sha, *, base=None, base_sha=None):
        self._require(pr.get("number") == number, "wrong_pull_request", "Unexpected pull request number")
        self._require(pr.get("state") == "open" and pr.get("merged") is False
                      and pr.get("draft") is False,
                      "pull_request_not_open", "Expected an open, non-draft, unmerged pull request")
        for side in ("head", "base"):
            actual = pr.get(side, {}).get("repo", {}).get("full_name", "")
            self._require(actual.lower() == self.repository.lower(), "wrong_repository",
                          "Pull request head and base must belong to the selected repository")
        self._require(pr["head"].get("ref") == branch and pr["head"].get("sha") == sha,
                      "wrong_head", "Pull request head does not match the frozen delivery")
        self._branch(pr["base"].get("ref"))
        if base is not None:
            self._require(pr["base"].get("ref") == base, "wrong_base", "Pull request targets a different branch")
        if base_sha is not None:
            self._require(pr["base"].get("sha") == base_sha, "wrong_base_sha",
                          "Pull request base changed from the frozen delivery baseline")

    def _verify_local_commit(self, sha, base_sha):
        result = self._run(["git", "--git-dir", str(self.git_dir), "cat-file", "-t", sha])
        self._require(result.returncode == 0 and result.stdout.strip() == "commit",
                      "missing_commit", "Frozen delivery is not a local commit")
        result = self._run(["git", "--git-dir", str(self.git_dir),
                            "merge-base", "--is-ancestor", base_sha, sha])
        self._require(result.returncode == 0, "invalid_ancestry",
                      "Frozen baseline must be an ancestor of the delivered commit")

    def _verify_registered_delivery(self, delivery):
        identifier = delivery.get("id")
        self._require(isinstance(identifier, str)
                      and re.fullmatch(r"[A-Za-z0-9_-]+", identifier),
                      "invalid_delivery", "Expected a frozen delivery identifier")
        # The manager owns <state>/repo.git and the adjacent state.json. An
        # arbitrary Git checkout plus caller-supplied JSON is not a handoff.
        self._require(self.git_dir.name == "repo.git", "unregistered_delivery",
                      "Publish requires the manager's state/repo.git directory")
        try:
            state = json.loads((self.git_dir.parent / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise GitHubAdapterError("unregistered_delivery",
                                     "Could not read the local delivery registry") from error
        records = state.get("deliveries") if isinstance(state, dict) else None
        record = records.get(identifier) if isinstance(records, dict) else None
        self._require(isinstance(record, dict) and record == delivery,
                      "unregistered_delivery", "Input must match the complete frozen delivery record")
        result = self._run(["git", "--git-dir", str(self.git_dir), "show-ref", "--verify", "--hash",
                            "refs/prototype/deliveries/" + identifier])
        self._require(result.returncode == 0 and result.stdout.strip() == delivery["sha"],
                      "delivery_ref_mismatch", "The immutable delivery ref does not match its record")

    def publish(self, delivery, title, body, base, previous_head=None, pull_number=None):
        self._require(isinstance(delivery, dict), "invalid_delivery", "Expected a delivery object")
        work_id = delivery.get("work_id")
        self._require(isinstance(work_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", work_id),
                      "invalid_work", "Invalid work identifier")
        sha, base_sha = self._sha(delivery.get("sha")), self._sha(delivery.get("base"))
        branch = "newgit/" + work_id
        self._branch(base)
        self._require(branch != base, "same_branch", "Delivery branch cannot also be its PR base")
        self._require(isinstance(title, str) and bool(title.strip()) and isinstance(body, str),
                      "invalid_text", "A title and string body are required")
        self._require((previous_head is None) == (pull_number is None), "invalid_update",
                      "Updating requires both a previous head SHA and a pull request number")
        if previous_head is not None:
            self._sha(previous_head)
            self._number(pull_number)
        self._verify_registered_delivery(delivery)
        self._verify_local_commit(sha, base_sha)
        publisher = self._context()
        remote_base = self._ref(base)
        self._require(self._ref_sha(remote_base, base) == base_sha, "wrong_base_sha",
                      "Target branch no longer matches the delivery baseline")
        remote_head = self._ref(branch, optional=True)
        if previous_head is None:
            self._require(remote_head is None, "branch_exists", "A new delivery branch must not exist")
        else:
            self._require(remote_head is not None
                          and self._ref_sha(remote_head, branch) == previous_head,
                          "wrong_head", "Remote branch no longer matches the expected previous head")
            existing = self._pr(pull_number)
            self._verify_pr(existing, pull_number, branch, previous_head)

        ref = f"refs/heads/{branch}"
        lease = f"--force-with-lease={ref}:{previous_head or ''}"
        # Scope credential selection to this command and use the same gh account
        # recorded above. No token is read, printed, or written by this adapter.
        push = self._run(["git", "--git-dir", str(self.git_dir), "-c", "credential.helper=", "-c",
                          "credential.helper=!gh auth git-credential", "push", "--porcelain", lease,
                          f"https://github.com/{self.repository}.git", f"{sha}:{ref}"])
        self._evidence("push", {"repository": self.repository, "publisher_login": publisher,
                                "ref": ref, "sha": sha, "expected_old_sha": previous_head,
                                "exit_code": push.returncode})
        self._require(push.returncode == 0, "push_failed", "Git push failed; no write was retried")
        self._require(self._ref_sha(self._ref(branch), branch) == sha,
                      "wrong_head", "Remote branch readback did not match the frozen delivery")

        endpoint = f"/repos/{self.repository}/pulls"
        if pull_number is None:
            created = self._api("POST", endpoint,
                                {"title": title, "body": body, "head": branch, "base": base, "draft": False})
            pull_number = self._number(created.get("number"))
        else:
            self._api("PATCH", f"{endpoint}/{pull_number}", {"title": title, "body": body, "base": base})
        for attempt in range(3):
            pr = self._pr(pull_number)
            # GitHub may still report the previous PR head after the branch ref
            # has caught up. Retry only that known value, never a different head
            # or a mismatched target, and never repeat either write.
            if (previous_head is not None and previous_head != sha
                    and pr.get("head", {}).get("sha") == previous_head):
                self._verify_pr(pr, pull_number, branch, previous_head,
                                base=base, base_sha=base_sha)
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
            self._verify_pr(pr, pull_number, branch, sha, base=base, base_sha=base_sha)
            break
        self._require(self._ref_sha(self._ref(base), base) == base_sha,
                      "wrong_base_sha", "Target branch moved during publication")
        self._evidence("published", {"repository": self.repository, "publisher_login": publisher,
                                     "delivery_id": delivery.get("id"), "work_id": work_id,
                                     "delivery_sha": sha, "base_sha": base_sha,
                                     "pull_number": pull_number, "head_ref": branch, "base_ref": base,
                                     "state": pr["state"], "merged": pr["merged"]})
        return pr

    def review(self, pr_number, commit_sha, body, *, expected_base_sha, expected_base_ref):
        self._number(pr_number)
        self._sha(commit_sha)
        self._sha(expected_base_sha)
        self._branch(expected_base_ref)
        self._require(isinstance(body, str) and bool(body.strip()), "invalid_text", "Review body is required")
        reviewer = self._context()
        pr = self._pr(pr_number)
        branch = pr.get("head", {}).get("ref")
        self._require(isinstance(branch, str) and re.fullmatch(r"newgit/[A-Za-z0-9_-]+", branch),
                      "invalid_branch", "Only newgit delivery branches may receive an adapter review")
        self._verify_pr(pr, pr_number, branch, commit_sha,
                        base=expected_base_ref, base_sha=expected_base_sha)
        endpoint = f"/repos/{self.repository}/pulls/{pr_number}/reviews"
        created = self._api("POST", endpoint,
                            {"commit_id": commit_sha, "body": body, "event": "COMMENT"})
        review_id = self._number(created.get("id"))
        result = self._api("GET", f"{endpoint}/{review_id}")
        self._require(result.get("id") == review_id and result.get("state") == "COMMENTED"
                      and result.get("commit_id") == commit_sha,
                      "wrong_review", "Review readback must be COMMENTED on the exact requested commit")
        self._require(result.get("user", {}).get("login", "").lower() == reviewer.lower(),
                      "wrong_reviewer", "Review author is not the authenticated GitHub account")
        self._require(result.get("body") == body, "wrong_review_body", "Review body changed during publication")
        current = self._pr(pr_number)
        self._verify_pr(current, pr_number, branch, commit_sha,
                        base=expected_base_ref, base_sha=expected_base_sha)
        self._evidence("reviewed", {"repository": self.repository, "reviewer_login": reviewer,
                                    "pull_number": pr_number, "review_id": review_id,
                                    "head_sha": commit_sha, "base_sha": expected_base_sha,
                                    "base_ref": expected_base_ref, "event": "COMMENT",
                                    "state": result["state"], "human_approval": False})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--git-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--delivery-file", type=Path, required=True)
    publish.add_argument("--title", required=True)
    publish.add_argument("--body-file", type=Path, required=True)
    publish.add_argument("--base", required=True)
    publish.add_argument("--previous-head")
    publish.add_argument("--pull-number", type=int)
    review = commands.add_parser("review")
    review.add_argument("--number", type=int, required=True)
    review.add_argument("--commit", required=True)
    review.add_argument("--base", required=True)
    review.add_argument("--base-sha", required=True)
    review.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        adapter = GitHubReviewAdapter(args.repository, args.git_dir, args.evidence_dir)
        body = args.body_file.read_text(encoding="utf-8")
        if args.command == "publish":
            delivery = json.loads(args.delivery_file.read_text(encoding="utf-8"))
            result = adapter.publish(delivery, args.title, body, args.base,
                                     previous_head=args.previous_head, pull_number=args.pull_number)
        else:
            result = adapter.review(args.number, args.commit, body,
                                    expected_base_ref=args.base, expected_base_sha=args.base_sha)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GitHubAdapterError as error:
        print(json.dumps({"error": error.code, "message": str(error)}, ensure_ascii=False))
        return 2
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"error": "input_error", "message": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
