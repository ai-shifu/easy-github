"""Acceptance survives interruptions between its Git ref and JSON record."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "prototype"), str(ROOT / "scripts")]
from newgit import Prototype, PrototypeError
from demo_support import PRICE, git, seed_project


class AcceptanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="accept-recovery-")
        self.root = Path(self.temp.name)
        self.source = seed_project(self.root)
        self.p = Prototype.initialize(self.source, self.root / "state")
        self.baseline = self.p.status()["team_sha"]
        work = self.p.start("author", "fixture", "Acceptance recovery fixture")
        (Path(work["workspace"]) / "checkout.py").write_text(PRICE)
        delivery = self.p.submit(work["id"], work["attempt"], handoff=True)
        self.review = self.p.review(delivery["id"], "reviewer")
        self.p.record_check(self.review["id"], self.review["candidate_sha"], "fixture", "passed",
                            "Synthetic gate for a persistence test, not a business test")
        self.state_file = self.p.state / "state.json"

    def tearDown(self):
        self.temp.cleanup()

    def disk(self):
        return json.loads(self.state_file.read_text())

    def accept(self, controller=None, reviewer="reviewer"):
        return (controller or self.p).accept(self.review["id"], reviewer)

    def interrupted_ref(self, *, applied):
        original = self.p._git

        def interrupt(*args, **kwargs):
            if args[:2] == ("update-ref", self.p.TEAM_REF):
                if applied:
                    original(*args, **kwargs)
                raise KeyboardInterrupt("Fixture interruption at ref transition")
            return original(*args, **kwargs)

        with patch.object(self.p, "_git", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.accept()

    def assert_complete(self, result):
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["candidate_sha"], self.review["candidate_sha"])
        self.assertEqual(self.p._team(), self.review["candidate_sha"])
        data = self.disk()
        self.assertTrue(data["reviews"][self.review["id"]]["accepted"])
        self.assertNotIn("pending_accept", data)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.baseline)

    def test_intent_write_failure_never_changes_ref(self):
        before = self.state_file.read_bytes()
        with patch.object(self.p, "_save", side_effect=OSError("Fixture disk full")):
            with self.assertRaises(OSError):
                self.accept()
        self.assertEqual(self.p._team(), self.baseline)
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assert_complete(self.accept())

    def test_unapplied_intent_is_cleared_without_accepting_on_status(self):
        self.interrupted_ref(applied=False)
        self.assertIn("pending_accept", self.disk())
        recovered = Prototype(self.p.state)
        status = recovered.status()
        self.assertEqual(status["team_sha"], self.baseline)
        self.assertFalse(status["reviews"][0].get("accepted"))
        self.assertNotIn("pending_accept", self.disk())
        self.assert_complete(self.accept(recovered))

    def test_applied_ref_is_recorded_on_next_process_status(self):
        self.interrupted_ref(applied=True)
        self.assertEqual(self.p._team(), self.review["candidate_sha"])
        self.assertFalse(self.disk()["reviews"][self.review["id"]].get("accepted"))
        recovered = Prototype(self.p.state)
        status = recovered.status()
        self.assertTrue(status["reviews"][0]["accepted"])
        self.assert_complete(self.accept(recovered))
        with self.assertRaises(PrototypeError) as rejected:
            self.accept(recovered, "other")
        self.assertEqual(rejected.exception.code, "wrong_reviewer")

    def test_final_state_write_failure_is_recovered_on_retry(self):
        original = self.p._save

        def fail_completion(data, path=None):
            if "pending_accept" not in data:
                raise OSError("Fixture failure before final state write")
            return original(data, path)

        with patch.object(self.p, "_save", side_effect=fail_completion):
            with self.assertRaises(OSError):
                self.accept()
        self.assertIn("pending_accept", self.disk())
        recovered = Prototype(self.p.state)
        with patch.object(recovered, "_git", wraps=recovered._git) as calls:
            self.assert_complete(self.accept(recovered))
        self.assertFalse(any(call.args[:2] == ("update-ref", self.p.TEAM_REF)
                             for call in calls.call_args_list))

    def test_lost_final_save_acknowledgement_is_idempotent(self):
        original = self.p._save

        def lost_ack(data, path=None):
            original(data, path)
            if "pending_accept" not in data:
                raise OSError("Fixture failure after durable state replacement")

        with patch.object(self.p, "_save", side_effect=lost_ack):
            with self.assertRaises(OSError):
                self.accept()
        self.assertNotIn("pending_accept", self.disk())
        recovered = Prototype(self.p.state)
        with patch.object(recovered, "_save", side_effect=AssertionError("Retry must not write")):
            self.assert_complete(self.accept(recovered))

    def test_unexpected_ref_drift_preserves_intent_and_external_ref(self):
        self.interrupted_ref(applied=True)
        tree = git(self.p.repo, "rev-parse", self.baseline + "^{tree}")
        external = self.p._commit(tree, [self.baseline], "External writer fixture")
        git(self.p.repo, "update-ref", self.p.TEAM_REF, external, self.review["candidate_sha"])
        before = self.state_file.read_bytes()
        with self.assertRaises(PrototypeError) as rejected:
            Prototype(self.p.state).status()
        self.assertEqual(rejected.exception.code, "acceptance_conflict")
        self.assertEqual(self.p._team(), external)
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_mismatched_intent_or_changed_checks_cannot_finish_acceptance(self):
        self.interrupted_ref(applied=True)
        original = self.disk()
        for alteration in ("intent", "checks"):
            data = json.loads(json.dumps(original))
            if alteration == "intent":
                data["pending_accept"]["reviewer"] = "different-reviewer"
            else:
                data["reviews"][self.review["id"]]["checks"]["fixture"]["status"] = "failed"
            self.state_file.write_text(json.dumps(data))
            before = self.state_file.read_bytes()
            with self.assertRaises(PrototypeError) as rejected:
                Prototype(self.p.state).status()
            self.assertEqual(rejected.exception.code, "acceptance_conflict")
            self.assertEqual(self.state_file.read_bytes(), before)
            self.assertEqual(self.p._team(), self.review["candidate_sha"])


if __name__ == "__main__":
    unittest.main()
