import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype"))
sys.path.insert(0, str(ROOT / "scripts"))

from newgit import Prototype, PrototypeError
from github_plan import publish_plan, bind_pr_readback, ContractError
from demo_support import INITIAL, PRICE, COUPON, seed_project, git
from run_demo import run_scenario


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="newgit-test-")
        self.root = Path(self.temp.name)
        self.source = seed_project(self.root)
        self.p = Prototype.initialize(self.source, self.root / "state")

    def tearDown(self):
        self.temp.cleanup()

    def delivery(self, owner="lin", content=PRICE, filename="checkout.py"):
        work = self.p.start(owner, "simulated", "fixture change")
        (Path(work["workspace"]) / filename).write_text(content)
        delivery = self.p.submit(work["id"], work["attempt"], handoff=True)
        return work, delivery

    def checked_review(self, delivery, reviewer="zhou"):
        review = self.p.review(delivery["id"], reviewer)
        self.assertEqual(review["status"], "ready")
        # Gate-focused tests use a labelled synthetic report; the scenario executes real checks.
        self.p.record_check(review["id"], review["candidate_sha"], "synthetic-gate", "passed",
                            "Test fixture report, not an executed business check")
        return review

    def assert_rejected(self, code, function, *args, **kwargs):
        with self.assertRaises(PrototypeError) as result:
            function(*args, **kwargs)
        self.assertEqual(result.exception.code, code)

    def test_delivery_is_frozen_without_changing_head_or_staging(self):
        work = self.p.start("lin", "simulated", "snapshot")
        directory = Path(work["workspace"])
        (directory / "README.md").write_text("Staged draft\n")
        git(directory, "add", "README.md")
        (directory / "checkout.py").write_text(PRICE)
        (directory / "private.env").write_text("FIXTURE_ONLY=not-a-secret\n")
        head, staging = git(directory, "rev-parse", "HEAD"), git(directory, "diff", "--cached")
        d = self.p.submit(work["id"], work["attempt"], handoff=True)
        (directory / "checkout.py").write_text(COUPON)
        self.assertEqual(git(self.p.repo, "show", d["sha"] + ":checkout.py"), PRICE.strip())
        self.assertEqual(git(directory, "rev-parse", "HEAD"), head)
        self.assertEqual(git(directory, "diff", "--cached"), staging)
        self.assertNotIn("private.env", git(self.p.repo, "ls-tree", "-r", "--name-only", d["sha"]))

    def test_external_commits_are_included_without_moving_their_head(self):
        work = self.p.start("lin", "simulated", "externally committed")
        directory = Path(work["workspace"])
        (directory / "checkout.py").write_text(PRICE)
        git(directory, "add", "checkout.py")
        git(directory, "-c", "commit.gpgsign=false", "commit", "-m", "External tool commit")
        head = git(directory, "rev-parse", "HEAD")
        d = self.p.submit(work["id"], work["attempt"], handoff=True)
        self.assertEqual(git(directory, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.p.repo, "show", d["sha"] + ":checkout.py"), PRICE.strip())

    def test_handoff_and_reviewer_boundaries(self):
        w = self.p.start("lin", "simulated", "handoff")
        self.assert_rejected("handoff_required", self.p.submit, w["id"], w["attempt"])
        d = self.p.submit(w["id"], w["attempt"], handoff=True)
        self.assert_rejected("self_review", self.p.review, d["id"], "lin")

    def test_check_must_match_candidate_and_pass(self):
        _, d = self.delivery()
        r = self.p.review(d["id"], "zhou")
        self.assert_rejected("checks_required", self.p.accept, r["id"], "zhou")
        self.assert_rejected("wrong_snapshot", self.p.record_check, r["id"], d["base"], "test", "passed")
        self.p.record_check(r["id"], r["candidate_sha"], "test", "failed")
        self.assert_rejected("checks_failed", self.p.accept, r["id"], "zhou")
        self.assert_rejected("wrong_reviewer", self.p.accept, r["id"], "other")

    def test_new_revision_invalidates_old_review(self):
        w, d = self.delivery()
        r = self.checked_review(d)
        (Path(w["workspace"]) / "README.md").write_text("New material after approval\n")
        self.p.submit(w["id"], w["attempt"], handoff=True)
        self.assert_rejected("superseded_delivery", self.p.accept, r["id"], "zhou")

    def test_starting_update_suspends_the_old_review(self):
        _, delivery = self.delivery()
        review = self.checked_review(delivery)
        self.p.prepare_update(delivery["id"])
        self.assert_rejected("stale_attempt", self.p.accept, review["id"], "zhou")

    def test_repair_retains_original_and_rejects_old_attempt(self):
        w, d = self.delivery("zhou", COUPON)
        other_w, other_d = self.delivery("lin")
        r = self.checked_review(other_d, "zhou")
        self.p.accept(r["id"], "zhou")
        draft = Path(w["workspace"]) / "draft.txt"
        draft.write_text("Not delivered\n")
        self.assertEqual(self.p.review(d["id"], "lin")["status"], "needs_update")
        repair = self.p.prepare_update(d["id"])
        self.assertEqual(draft.read_text(), "Not delivered\n")
        self.assertFalse((Path(repair["workspace"]) / "draft.txt").exists())
        context = json.loads(Path(repair["context_file"]).read_text())
        self.assertEqual(context["delivery_sha"], d["sha"])
        self.assertEqual(context["latest_team_sha"], self.p.status()["team_sha"])
        self.assert_rejected("stale_attempt", self.p.submit, w["id"], w["attempt"], handoff=True)

    def test_concurrent_accept_does_not_lose_changes(self):
        _, a = self.delivery("lin", PRICE)
        _, b = self.delivery("zhou", "New documentation\n", "README.md")
        ra, rb = self.checked_review(a, "zhou"), self.checked_review(b, "lin")
        processes = []
        for review, who in ((ra, "zhou"), (rb, "lin")):
            processes.append(subprocess.Popen(
                [sys.executable, str(ROOT / "prototype/newgit.py"), "--state", str(self.p.state),
                 "accept", "--review", review["id"], "--reviewer", who],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        outcomes = [(p, p.communicate()) for p in processes]
        self.assertEqual(sorted(p.returncode for p, _ in outcomes), [0, 1])
        losing = next(i for i, (p, _) in enumerate(outcomes) if p.returncode != 0)
        failure = json.loads(outcomes[losing][1][0])
        self.assertEqual(failure["error"]["code"], "stale_review")
        delivery, reviewer = ((a, "zhou"), (b, "lin"))[losing]
        fresh = self.checked_review(delivery, reviewer)
        self.p.accept(fresh["id"], reviewer)
        team = self.p.status()["team_sha"]
        self.assertEqual(git(self.p.repo, "show", team + ":checkout.py"), PRICE.strip())
        self.assertEqual(git(self.p.repo, "show", team + ":README.md"), "New documentation")
        self.assertEqual(git(self.source, "show", "HEAD:checkout.py"), INITIAL.strip())

    def test_cli_rejection_is_structured_and_nonzero(self):
        result = subprocess.run([sys.executable, str(ROOT / "prototype/newgit.py"),
                                 "--state", str(self.root / "uninitialized"), "status"],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "not_initialized")


class ScenarioTest(unittest.TestCase):
    def test_two_person_full_scenario(self):
        with tempfile.TemporaryDirectory(prefix="newgit-scenario-") as directory:
            report = run_scenario(directory)
            self.assertEqual(report["result"], "passed")
            self.assertEqual([report["final"]["plain"], report["final"]["with_coupon"]], [129, 109])
            self.assertEqual(report["github"]["live_requests"], 0)
            self.assertTrue(report["github"]["changed_head_rejected"])


class GitHubContractTests(unittest.TestCase):
    def setUp(self):
        self.delivery = {"work_id": "w-example", "sha": "a" * 40, "revision": 1}
        self.plan = publish_plan("example/project", self.delivery, "Example")
        self.response = {"number": 42, "state": "open", "draft": False, "merged": False,
                         "head": {"sha": "a" * 40, "ref": "newgit/w-example"},
                         "base": {"ref": "prototype-team", "repo": {"full_name": "example/project"}}}

    def test_head_drift_and_wrong_repository_are_rejected(self):
        for location in ("head", "repository", "number"):
            response, plan = copy.deepcopy(self.response), copy.deepcopy(self.plan)
            if location == "head":
                response["head"]["sha"] = "b" * 40
            elif location == "repository":
                response["base"]["repo"]["full_name"] = "someone/else"
            else:
                plan["pull_number"] = 99
            with self.assertRaises(ContractError):
                bind_pr_readback(plan, response)

    def test_publication_plan_is_frozen_and_has_no_merge(self):
        plan = publish_plan("example/project", {**self.delivery, "revision": 2}, "Revision",
                            previous_head="b" * 40, pull_number=42)
        self.assertFalse(plan["executed"])
        self.assertEqual(plan["steps"][0]["expected_old_sha"], "b" * 40)
        self.assertEqual(plan["steps"][0]["commit"], self.delivery["sha"])
        self.assertTrue(all(step["operation"] in ("git_push_with_lease", "github_request")
                            for step in plan["steps"]))
        self.assertTrue(all("/merge" not in step.get("path", "") for step in plan["steps"]))
        self.assertEqual(bind_pr_readback(plan, self.response)["merge_status"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
