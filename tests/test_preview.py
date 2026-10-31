"""Pending deliveries can be combined and repaired without accepting either one."""
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
from demo_support import COUPON, PRICE, git, seed_project


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="newgit-preview-")
        self.root = Path(self.temp.name)
        self.source = seed_project(self.root)
        self.p = Prototype.initialize(self.source, self.root / "state")
        self.team = self.p.status()["team_sha"]
        self.a, self.da = self.delivery("lin", PRICE)
        self.b, self.db = self.delivery("zhou", COUPON)

    def tearDown(self):
        self.temp.cleanup()

    def delivery(self, owner, content, filename="checkout.py"):
        work = self.p.start(owner, "external-fixture", "pending change")
        (Path(work["workspace"]) / filename).write_text(content)
        return work, self.p.submit(work["id"], work["attempt"], handoff=True)

    def rejected(self, code, function, *args, **kwargs):
        with self.assertRaises(PrototypeError) as result:
            function(*args, **kwargs)
        self.assertEqual(result.exception.code, code)

    def assert_team_unchanged(self):
        self.assertEqual(self.p.status()["team_sha"], self.team)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.team)

    def repair(self):
        update = self.p.prepare_update(self.db["id"], onto_delivery_id=self.da["id"])
        (Path(update["workspace"]) / "checkout.py").write_text(PRICE + "\n# Reconciled coupon fixture\n")
        delivery = self.p.submit(update["id"], update["attempt"], handoff=True)
        return update, delivery

    def test_pending_conflict_does_not_move_team(self):
        review = self.p.review(self.db["id"], "lin", onto_delivery_id=self.da["id"])
        self.assertEqual(review["status"], "needs_update")
        self.assertEqual(review["overlapping_paths"], ["checkout.py"])
        self.assertTrue(review["preview_only"])
        self.assertEqual(review["onto_delivery_id"], self.da["id"])
        self.assertEqual(review["comparison_sha"], self.da["sha"])
        self.assertEqual(review["team_sha"], self.team)
        self.rejected("preview_only", self.p.accept, review["id"], "lin")
        self.assert_team_unchanged()

    def test_repair_preserves_original_and_keeps_preview_dependency(self):
        old = Path(self.b["workspace"])
        (old / "draft.txt").write_text("Undelivered original draft\n")
        update, delivery = self.repair()
        self.assertNotEqual(update["workspace"], str(old))
        self.assertEqual((old / "checkout.py").read_text(), COUPON)
        self.assertEqual((old / "draft.txt").read_text(), "Undelivered original draft\n")
        self.assertFalse((Path(update["workspace"]) / "draft.txt").exists())
        self.assertEqual(update["base"], self.da["sha"])
        self.assertEqual(update["team_sha"], self.team)
        self.assertNotIn(Path(update["workspace"]), Path(update["context_file"]).parents)
        context = json.loads(Path(update["context_file"]).read_text())
        self.assertEqual(context["latest_team_sha"], self.team)
        self.assertEqual(context["comparison_sha"], self.da["sha"])
        self.assertEqual(context["onto_delivery_id"], self.da["id"])
        self.assertTrue(context["comparison_diff"])
        self.assertEqual(delivery["revision"], 2)
        self.assertEqual(delivery["onto_delivery_id"], self.da["id"])
        self.assertTrue(delivery["preview_only"])
        current = next(w for w in self.p.status()["workings"] if w["id"] == self.b["id"])
        self.assertEqual(current["attempts"][-1]["onto_delivery_id"], self.da["id"])
        review = self.p.review(delivery["id"], "lin")  # Omitting --onto cannot remove the dependency.
        self.assertEqual(review["status"], "ready")
        self.assertTrue(review["preview_only"])
        self.assertEqual(review["candidate_sha"], delivery["sha"])
        self.p.record_check(review["id"], review["candidate_sha"], "synthetic-preview", "passed")
        self.rejected("preview_only", self.p.accept, review["id"], "lin")
        again = self.p.prepare_update(delivery["id"])
        self.assertEqual(again["base"], self.da["sha"])
        self.assertEqual(again["onto_delivery_id"], self.da["id"])
        self.assert_team_unchanged()

    def test_disjoint_pending_changes_form_preview_candidate(self):
        _, documentation = self.delivery("third", "Preview documentation\n", "README.md")
        review = self.p.review(documentation["id"], "lin", self.da["id"])
        self.assertEqual(review["status"], "ready")
        self.assertEqual(git(self.p.repo, "show", review["candidate_sha"] + ":checkout.py"), PRICE.strip())
        self.assertEqual(git(self.p.repo, "show", review["candidate_sha"] + ":README.md"), "Preview documentation")
        self.assertNotIn("diff --git a/checkout.py", review["diff"])
        self.rejected("preview_only", self.p.accept, review["id"], "lin")
        self.assert_team_unchanged()

    def test_new_dependency_revision_rejects_implicit_reuse(self):
        update, delivery = self.repair()
        review = self.p.review(delivery["id"], "lin")
        (Path(self.a["workspace"]) / "README.md").write_text("New revision of dependency\n")
        newer = self.p.submit(self.a["id"], self.a["attempt"], handoff=True)
        self.rejected("superseded_dependency", self.p.review, delivery["id"], "lin")
        self.rejected("superseded_dependency", self.p.prepare_update, delivery["id"])
        self.rejected("superseded_dependency", self.p.submit, update["id"], update["attempt"], handoff=True)
        self.rejected("superseded_dependency", self.p.record_check,
                      review["id"], review["candidate_sha"], "outdated", "passed")
        self.rejected("superseded_dependency", self.p.review, self.db["id"], "lin", self.da["id"])
        explicit = self.p.prepare_update(delivery["id"], onto_delivery_id=newer["id"])
        self.assertEqual(explicit["base"], newer["sha"])
        self.assertEqual(explicit["onto_delivery_id"], newer["id"])
        self.assert_team_unchanged()

    def test_same_work_dependency_is_rejected(self):
        self.rejected("invalid_dependency", self.p.review, self.da["id"], "zhou", self.da["id"])
        self.rejected("invalid_dependency", self.p.prepare_update, self.da["id"], self.da["id"])
        self.assert_team_unchanged()

    def test_cli_exposes_preview_review_and_update(self):
        command = [sys.executable, "-B", str(ROOT / "prototype/newgit.py"), "--state", str(self.p.state)]
        for operation in ("review", "update"):
            args = command + [operation, "--delivery", self.db["id"], "--onto-delivery", self.da["id"]]
            if operation == "review":
                args += ["--reviewer", "lin"]
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            response = json.loads(result.stdout)
            self.assertTrue(response["preview_only"])
            self.assertEqual(response["onto_delivery_id"], self.da["id"])
            self.assertEqual(response["team_sha"], self.team)
        self.assert_team_unchanged()


if __name__ == "__main__":
    unittest.main()
