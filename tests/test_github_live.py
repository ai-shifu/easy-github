import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prototype.github_live import GitHubAdapterError, GitHubReviewAdapter


REPOSITORY = "fixture-user/newgit-integration-fixture"
BASE = "a" * 40
FIRST = "b" * 40
SECOND = "c" * 40
STACK_BASE = "d" * 40


class FakeTransport:
    """A local subprocess double; no Git or GitHub operation is executed."""

    def __init__(self):
        self.calls = []
        self.private = True
        self.full_name = REPOSITORY
        self.branches = {"prototype-team": BASE, "newgit/price": STACK_BASE}
        self.pull = None
        self.review_result = None
        self.readback_head = None
        self.pr_readback_heads = []
        self.readback_review_sha = None
        self.fail_push = False
        self.user = {"login": "fixture-user", "id": 123}
        self.delivery_refs = {}

    def result(self, args, value, code=0):
        text = value if isinstance(value, str) else json.dumps(value)
        return subprocess.CompletedProcess(args, code, text, "")

    def pr(self):
        result = copy.deepcopy(self.pull)
        result["head"]["sha"] = self.readback_head or self.branches[result["head"]["ref"]]
        result["base"]["sha"] = self.branches[result["base"]["ref"]]
        return result

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), dict(kwargs)))
        if args[0] == "git":
            if "show-ref" in args:
                sha = self.delivery_refs.get(args[-1])
                return self.result(args, (sha + "\n") if sha else "", 0 if sha else 1)
            if "cat-file" in args:
                return self.result(args, "commit\n")
            if "merge-base" in args:
                return self.result(args, "")
            if "push" in args:
                if self.fail_push:
                    return self.result(args, "", 1)
                lease = next(item for item in args if item.startswith("--force-with-lease="))
                ref, old = lease.split("=", 1)[1].split(":", 1)
                sha, target = args[-1].split(":", 1)
                branch = ref.removeprefix("refs/heads/")
                if target != ref or self.branches.get(branch, "") != old:
                    return self.result(args, "", 1)
                self.branches[branch] = sha
                return self.result(args, "pushed\n")
            raise AssertionError(f"Unexpected Git command: {args}")
        if args[0] != "gh" or args[1] != "api":
            raise AssertionError(f"Unexpected command: {args}")
        method = args[args.index("--method") + 1]
        path = args[args.index("--method") + 2]
        payload = json.loads(kwargs["input"]) if kwargs.get("input") is not None else None
        prefix = f"/repos/{REPOSITORY}"
        if method == "GET" and path == prefix:
            return self.result(args, {"full_name": self.full_name, "private": self.private})
        if method == "GET" and path == "/user":
            return self.result(args, self.user)
        if method == "GET" and path.startswith(prefix + "/git/ref/heads/"):
            branch = path.removeprefix(prefix + "/git/ref/heads/")
            if branch not in self.branches:
                return self.result(args, {"status": "404", "message": "Not Found"}, 1)
            return self.result(args, {"ref": f"refs/heads/{branch}",
                                      "object": {"type": "commit", "sha": self.branches[branch]}})
        if method == "POST" and path == prefix + "/pulls":
            self.pull = {"number": 7, "state": "open", "merged": False, "draft": False,
                         "head": {"ref": payload["head"], "repo": {"full_name": REPOSITORY}},
                         "base": {"ref": payload["base"], "repo": {"full_name": REPOSITORY}},
                         "title": payload["title"], "body": payload["body"], "user": self.user}
            return self.result(args, self.pr())
        if method == "PATCH" and path == prefix + "/pulls/7":
            self.pull["base"]["ref"] = payload["base"]
            self.pull.update({key: payload[key] for key in ("title", "body")})
            return self.result(args, self.pr())
        if method == "GET" and path == prefix + "/pulls/7":
            result = self.pr()
            if self.pr_readback_heads:
                result["head"]["sha"] = self.pr_readback_heads.pop(0)
            return self.result(args, result)
        if method == "POST" and path == prefix + "/pulls/7/reviews":
            self.review_result = {"id": 99, "state": "COMMENTED", "commit_id": payload["commit_id"],
                                  "body": payload["body"], "user": self.user}
            return self.result(args, self.review_result)
        if method == "GET" and path == prefix + "/pulls/7/reviews/99":
            result = copy.deepcopy(self.review_result)
            if self.readback_review_sha is not None:
                result["commit_id"] = self.readback_review_sha
            return self.result(args, result)
        raise AssertionError(f"Unexpected GitHub request: {method} {path}")

    def writes(self):
        return [(args, kwargs) for args, kwargs in self.calls
                if args[0] == "gh" and args[args.index("--method") + 1] != "GET"]

    def pushes(self):
        return [args for args, _ in self.calls if args[0] == "git" and "push" in args]


class GitHubLiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git_dir = self.root / "state" / "repo.git"
        self.git_dir.mkdir(parents=True)
        self.transport = FakeTransport()
        self.adapter = GitHubReviewAdapter(REPOSITORY, self.git_dir, self.root / "evidence",
                                           runner=self.transport)
        self.delivery = {"id": "d-1", "work_id": "coupon", "revision": 1,
                         "sha": FIRST, "base": BASE, "owner": "pretend-human", "attempt": 1}
        self.records = {}
        self.register(self.delivery)

    def register(self, delivery):
        self.records[delivery["id"]] = copy.deepcopy(delivery)
        (self.git_dir.parent / "state.json").write_text(json.dumps({"deliveries": self.records}))
        self.transport.delivery_refs["refs/prototype/deliveries/" + delivery["id"]] = delivery["sha"]

    def publish(self):
        return self.adapter.publish(self.delivery, "Coupon change", "Line one\n\nLine two\n", "prototype-team")

    def test_repository_dot_segments_are_rejected_before_transport(self):
        for owner in (".", ".."):
            with self.subTest(owner=owner):
                self.assert_error("invalid_repository", lambda: GitHubReviewAdapter(
                    owner + "/newgit-integration-fixture", self.git_dir,
                    self.root / "evidence", runner=self.transport))
        self.assertEqual([], self.transport.calls)

    def test_api_scope_requires_complete_repository_path_segment(self):
        for path in ("/repos/" + REPOSITORY + "-other/pulls",
                     "/repos/" + REPOSITORY + "/../other/pulls"):
            with self.subTest(path=path):
                self.assert_error("unexpected_endpoint", lambda: self.adapter._api("POST", path, {}))
        self.assertEqual([], self.transport.calls)

    def assert_error(self, code, action):
        with self.assertRaises(GitHubAdapterError) as caught:
            action()
        self.assertEqual(code, caught.exception.code)

    def test_rejects_non_test_repository_without_transport_calls(self):
        self.assert_error("not_test_repository", lambda: GitHubReviewAdapter(
            "fixture-user/real-project", self.root, self.root / "other", runner=self.transport))
        self.assertEqual([], self.transport.calls)

    def test_rejects_non_private_repository_before_mutation(self):
        self.transport.private = False
        self.assert_error("not_private", self.publish)
        self.assertEqual([], self.transport.pushes())
        self.assertEqual([], self.transport.writes())

    def test_publish_binds_readback_and_records_actual_account(self):
        pr = self.publish()
        self.assertEqual((FIRST, BASE), (pr["head"]["sha"], pr["base"]["sha"]))
        self.assertEqual("Line one\n\nLine two\n", pr["body"])
        push = self.transport.pushes()[0]
        self.assertIn("--force-with-lease=refs/heads/newgit/coupon:", push)
        self.assertEqual(FIRST + ":refs/heads/newgit/coupon", push[-1])
        self.assertTrue(all(kwargs["shell"] is False for _, kwargs in self.transport.calls))
        post_args, post_kwargs = self.transport.writes()[0]
        self.assertEqual(["--input", "-"], post_args[-2:])
        self.assertEqual(pr["body"], json.loads(post_kwargs["input"])["body"])
        evidence = [json.loads(path.read_text()) for path in (self.root / "evidence").glob("*.json")]
        published = next(item for item in evidence if "publisher_login" in item and "pull_number" in item)
        self.assertEqual("fixture-user", published["publisher_login"])
        self.assertNotEqual(self.delivery["owner"], published["publisher_login"])
        gets = [item for item in evidence if item.get("method") == "GET"]
        self.assertTrue(any(item["path"].endswith("/pulls/7") for item in gets))

    def test_new_branch_must_not_already_exist_even_at_identical_sha(self):
        self.transport.branches["newgit/coupon"] = FIRST
        self.assert_error("branch_exists", self.publish)
        self.assertEqual([], self.transport.pushes())

    def test_refuses_main_target(self):
        self.assert_error("invalid_branch", lambda: self.adapter.publish(
            self.delivery, "Title", "Body", "main"))
        self.assertEqual([], self.transport.calls)

    def test_refuses_wrong_frozen_base(self):
        self.transport.branches["prototype-team"] = SECOND
        self.assert_error("wrong_base_sha", self.publish)
        self.assertEqual([], self.transport.pushes())

    def test_tampered_delivery_fields_fail_before_any_transport_call(self):
        for field, value in (("id", "d-unregistered"), ("sha", SECOND), ("base", STACK_BASE),
                             ("work_id", "other-work"), ("revision", 2), ("attempt", 2),
                             ("owner", "other-owner"), ("summary", "Added outside the handoff")):
            with self.subTest(field=field):
                altered = {**self.delivery, field: value}
                self.assert_error("unregistered_delivery", lambda: self.adapter.publish(
                    altered, "Title", "Body", "prototype-team"))
                self.assertEqual([], self.transport.calls)

    def test_missing_or_invalid_registry_fails_before_any_transport_call(self):
        registry = self.git_dir.parent / "state.json"
        for content in (None, "not-json", "[]", '{"deliveries": {}}'):
            with self.subTest(content=content):
                if content is None:
                    registry.unlink()
                else:
                    registry.write_text(content)
                self.assert_error("unregistered_delivery", self.publish)
                self.assertEqual([], self.transport.calls)

    def test_registry_cannot_be_reused_with_a_different_adjacent_git_directory(self):
        other = self.git_dir.parent / "other.git"
        other.mkdir()
        adapter = GitHubReviewAdapter(REPOSITORY, other, self.root / "other-evidence",
                                      runner=self.transport)
        self.assert_error("unregistered_delivery", lambda: adapter.publish(
            self.delivery, "Title", "Body", "prototype-team"))
        self.assertEqual([], self.transport.calls)

    def test_missing_or_changed_delivery_ref_fails_before_github_calls(self):
        ref = "refs/prototype/deliveries/" + self.delivery["id"]
        for sha in (None, SECOND):
            with self.subTest(sha=sha):
                self.transport.calls.clear()
                if sha is None:
                    self.transport.delivery_refs.pop(ref, None)
                else:
                    self.transport.delivery_refs[ref] = sha
                self.assert_error("delivery_ref_mismatch", self.publish)
                self.assertTrue(all(args[0] == "git" and "show-ref" in args
                                    for args, _ in self.transport.calls))
                self.assertEqual([], self.transport.pushes())

    def test_changed_registry_and_input_still_require_original_immutable_ref(self):
        altered = {**self.delivery, "sha": SECOND}
        (self.git_dir.parent / "state.json").write_text(json.dumps({
            "deliveries": {altered["id"]: altered}}))
        self.assert_error("delivery_ref_mismatch", lambda: self.adapter.publish(
            altered, "Title", "Body", "prototype-team"))
        self.assertTrue(all(args[0] == "git" for args, _ in self.transport.calls))
        self.assertEqual([], self.transport.pushes())

    def test_manager_delivery_and_real_git_ref_can_be_published_with_fake_remote(self):
        from prototype.newgit import Prototype
        from scripts.demo_support import seed_project

        source = seed_project(self.root)
        manager = Prototype.initialize(source, self.root / "actual-state")
        work = manager.start("alice", "offline-fixture", "Change price")
        (Path(work["workspace"]) / "checkout.py").write_text(
            "def checkout_total(coupon_discount=0):\n    return 129\n")
        delivery = manager.submit(work["id"], work["attempt"], "Offline fixture", handoff=True)
        self.transport.branches["prototype-team"] = delivery["base"]

        def local_git_and_fake_remote(args, **kwargs):
            if args[0] == "git" and "push" not in args:
                return subprocess.run(args, **kwargs)
            return self.transport(args, **kwargs)

        adapter = GitHubReviewAdapter(REPOSITORY, manager.repo, self.root / "actual-evidence",
                                      runner=local_git_and_fake_remote)
        pr = adapter.publish(delivery, "Price", "Actual local handoff, fake remote", "prototype-team")
        self.assertEqual(delivery["sha"], pr["head"]["sha"])
        self.assertEqual(str(manager.repo), self.transport.pushes()[0][2])

    def test_update_uses_exact_lease_and_can_make_stacked_pr(self):
        self.publish()
        replacement = {**self.delivery, "id": "d-2", "sha": SECOND, "base": STACK_BASE,
                       "revision": 2, "attempt": 2}
        self.register(replacement)
        pr = self.adapter.publish(replacement, "Updated", "New\nbody", "newgit/price",
                                  previous_head=FIRST, pull_number=7)
        self.assertIn("--force-with-lease=refs/heads/newgit/coupon:" + FIRST, self.transport.pushes()[-1])
        self.assertEqual((SECOND, STACK_BASE), (pr["head"]["sha"], pr["base"]["sha"]))
        self.assertEqual("newgit/price", pr["base"]["ref"])

    def test_stale_update_head_is_rejected_before_push(self):
        self.publish()
        self.transport.branches["newgit/coupon"] = SECOND
        count = len(self.transport.pushes())
        self.assert_error("wrong_head", lambda: self.adapter.publish(
            self.delivery, "Title", "Body", "prototype-team", previous_head=FIRST, pull_number=7))
        self.assertEqual(count, len(self.transport.pushes()))

    def test_update_retries_previous_pr_head_until_new_head_is_visible(self):
        self.publish()
        replacement = {**self.delivery, "id": "d-2", "sha": SECOND, "revision": 2}
        self.register(replacement)
        # The first GET is the preflight; only the GETs after PATCH may retry.
        self.transport.pr_readback_heads = [FIRST, FIRST, SECOND]
        self.transport.calls.clear()
        with patch("prototype.github_live.time.sleep") as sleep:
            pr = self.adapter.publish(replacement, "Updated", "Body", "prototype-team",
                                      previous_head=FIRST, pull_number=7)
        self.assertEqual(SECOND, pr["head"]["sha"])
        sleep.assert_called_once_with(0.5)
        self.assertEqual([], self.transport.pr_readback_heads)
        self.assertEqual(1, len(self.transport.pushes()))
        self.assertEqual(1, len(self.transport.writes()))

    def test_update_stops_after_bounded_reads_of_previous_pr_head(self):
        self.publish()
        replacement = {**self.delivery, "id": "d-2", "sha": SECOND, "revision": 2}
        self.register(replacement)
        self.transport.pr_readback_heads = [FIRST, FIRST, FIRST, FIRST, SECOND]
        self.transport.calls.clear()
        with patch("prototype.github_live.time.sleep") as sleep:
            self.assert_error("wrong_head", lambda: self.adapter.publish(
                replacement, "Updated", "Body", "prototype-team",
                previous_head=FIRST, pull_number=7))
        self.assertEqual(2, sleep.call_count)
        self.assertEqual([SECOND], self.transport.pr_readback_heads)
        self.assertEqual(1, len(self.transport.pushes()))
        self.assertEqual(1, len(self.transport.writes()))

    def test_update_rejects_third_pr_head_without_retry(self):
        self.publish()
        replacement = {**self.delivery, "id": "d-2", "sha": SECOND, "revision": 2}
        self.register(replacement)
        self.transport.pr_readback_heads = [FIRST, STACK_BASE, SECOND]
        self.transport.calls.clear()
        with patch("prototype.github_live.time.sleep") as sleep:
            self.assert_error("wrong_head", lambda: self.adapter.publish(
                replacement, "Updated", "Body", "prototype-team",
                previous_head=FIRST, pull_number=7))
        sleep.assert_not_called()
        self.assertEqual([SECOND], self.transport.pr_readback_heads)
        self.assertEqual(1, len(self.transport.pushes()))
        self.assertEqual(1, len(self.transport.writes()))

    def test_final_pr_readback_must_match_published_head(self):
        self.transport.readback_head = SECOND
        self.assert_error("wrong_head", self.publish)
        self.assertEqual(1, len(self.transport.pushes()))
        self.assertEqual(1, len(self.transport.writes()))

    def test_push_failure_does_not_retry_or_create_pr(self):
        self.transport.fail_push = True
        self.assert_error("push_failed", self.publish)
        self.assertEqual(1, len(self.transport.pushes()))
        self.assertEqual([], self.transport.writes())

    def test_review_is_comment_on_exact_head_with_readback(self):
        self.publish()
        result = self.adapter.review(7, FIRST, "AI review from Claude Code\nNo human approval.\n",
                                     expected_base_sha=BASE, expected_base_ref="prototype-team")
        self.assertEqual("COMMENTED", result["state"])
        self.assertEqual(FIRST, result["commit_id"])
        _, kwargs = self.transport.writes()[-1]
        self.assertEqual({"event": "COMMENT", "commit_id": FIRST, "body": result["body"]},
                         json.loads(kwargs["input"]))
        evidence = [json.loads(path.read_text()) for path in (self.root / "evidence").glob("*.json")]
        recorded = next(item for item in evidence if item.get("review_id") == 99)
        self.assertEqual("fixture-user", recorded["reviewer_login"])
        self.assertEqual(BASE, recorded["base_sha"])
        self.assertEqual("prototype-team", recorded["base_ref"])
        self.assertFalse(recorded["human_approval"])

    def test_review_rejects_stale_head_before_posting(self):
        self.publish()
        count = len(self.transport.writes())
        self.assert_error("wrong_head", lambda: self.adapter.review(
            7, SECOND, "Stale review", expected_base_sha=BASE, expected_base_ref="prototype-team"))
        self.assertEqual(count, len(self.transport.writes()))

    def test_review_rejects_changed_base_sha_before_posting(self):
        self.publish()
        self.transport.branches["prototype-team"] = STACK_BASE
        self.assertEqual(FIRST, self.transport.pr()["head"]["sha"])
        count = len(self.transport.writes())
        self.assert_error("wrong_base_sha", lambda: self.adapter.review(
            7, FIRST, "Reviewed the earlier base", expected_base_sha=BASE,
            expected_base_ref="prototype-team"))
        self.assertEqual(count, len(self.transport.writes()))

    def test_review_rejects_changed_base_ref_even_with_identical_sha(self):
        self.publish()
        self.transport.branches["newgit/price"] = BASE
        self.transport.pull["base"]["ref"] = "newgit/price"
        self.assertEqual(FIRST, self.transport.pr()["head"]["sha"])
        count = len(self.transport.writes())
        self.assert_error("wrong_base", lambda: self.adapter.review(
            7, FIRST, "Reviewed a different target", expected_base_sha=BASE,
            expected_base_ref="prototype-team"))
        self.assertEqual(count, len(self.transport.writes()))

    def test_review_requires_explicit_reviewed_base(self):
        with self.assertRaises(TypeError):
            self.adapter.review(7, FIRST, "Missing baseline")
        self.assertEqual([], self.transport.calls)

    def test_review_rejects_wrong_readback_sha_without_retry(self):
        self.publish()
        self.transport.readback_review_sha = SECOND
        self.assert_error("wrong_review", lambda: self.adapter.review(
            7, FIRST, "Review", expected_base_sha=BASE, expected_base_ref="prototype-team"))
        review_posts = [args for args, _ in self.transport.writes() if args[-3].endswith("/reviews")]
        self.assertEqual(1, len(review_posts))

    def test_other_repository_in_pr_is_rejected(self):
        self.publish()
        self.transport.pull["head"]["repo"]["full_name"] = "someone/newgit-integration-other"
        count = len(self.transport.writes())
        self.assert_error("wrong_repository", lambda: self.adapter.review(
            7, FIRST, "Review", expected_base_sha=BASE, expected_base_ref="prototype-team"))
        self.assertEqual(count, len(self.transport.writes()))

    def test_adapter_exposes_no_merge_or_approve_operation(self):
        self.publish()
        self.adapter.review(7, FIRST, "Read-only analysis from Codex",
                            expected_base_sha=BASE, expected_base_ref="prototype-team")
        self.assertFalse(hasattr(self.adapter, "merge"))
        self.assertFalse(hasattr(self.adapter, "approve"))
        for args, kwargs in self.transport.calls:
            if args[0] == "gh":
                path = args[args.index("--method") + 2]
                self.assertNotIn("/merge", path)
                if kwargs.get("input"):
                    self.assertNotEqual("APPROVE", json.loads(kwargs["input"]).get("event"))
            else:
                self.assertNotIn("merge", args)
        self.assertTrue(all(args[-1].endswith(":refs/heads/newgit/coupon")
                            for args in self.transport.pushes()))

    def test_recorded_api_evidence_redacts_token_fields(self):
        self.transport.user["access_token"] = "sensitive-value"
        self.publish()
        text = "\n".join(path.read_text() for path in (self.root / "evidence").glob("*.json"))
        self.assertNotIn("sensitive-value", text)
        self.assertIn("[redacted]", text)


if __name__ == "__main__":
    unittest.main()
