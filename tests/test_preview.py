"""Pending deliveries can be combined and repaired without accepting either one."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype"))
sys.path.insert(0, str(ROOT / "scripts"))

from newgit import Prototype, PrototypeError
from demo_support import COMBINED, COUPON, PRICE, attach_check, git, seed_project


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

    def test_accepted_dependency_can_be_updated_reviewed_and_accepted(self):
        preview_attempt, preview_delivery = self.repair()
        old_review = self.p.review(preview_delivery["id"], "lin")
        a_review = self.p.review(self.da["id"], "zhou")
        self.assertEqual(attach_check(self.p, a_review, 129, 129)["status"], "passed")
        self.p.accept(a_review["id"], "zhou")
        # Acceptance of A does not turn an existing preview into approval of B.
        self.rejected("preview_only", self.p.accept, old_review["id"], "lin")

        update = self.p.prepare_update(preview_delivery["id"])
        self.assertEqual(update["base"], a_review["candidate_sha"])
        context = json.loads(Path(update["context_file"]).read_text())
        work = next(w for w in self.p.status()["workings"] if w["id"] == self.b["id"])
        for record in (update, context, work, work["attempts"][-1]):
            self.assertNotIn("onto_delivery_id", record)
            self.assertNotIn("preview_only", record)
        self.assertTrue(work["attempts"][-2]["preview_only"])
        self.assertEqual((Path(preview_attempt["workspace"]) / "checkout.py").read_text(),
                         PRICE + "\n# Reconciled coupon fixture\n")
        (Path(update["workspace"]) / "checkout.py").write_text(COMBINED)
        delivery = self.p.submit(update["id"], update["attempt"], handoff=True)
        review = self.p.review(delivery["id"], "lin")
        for record in (delivery, review):
            self.assertNotIn("onto_delivery_id", record)
            self.assertNotIn("preview_only", record)
        self.assertEqual(review["status"], "ready")
        self.assertEqual(attach_check(self.p, review, 129, 109)["status"], "passed")
        self.p.accept(review["id"], "lin")
        self.assertEqual(self.p.status()["team_sha"], review["candidate_sha"])
        self.assertEqual(git(self.p.repo, "show", self.p.TEAM_REF + ":checkout.py"), COMBINED.strip())
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.team)

    def test_accepted_dependency_uses_current_team_despite_newer_pending_revision(self):
        _, delivery = self.repair()
        a_review = self.p.review(self.da["id"], "zhou")
        attach_check(self.p, a_review, 129, 129)
        self.p.accept(a_review["id"], "zhou")
        _, documentation = self.delivery("third", "Accepted documentation\n", "README.md")
        doc_review = self.p.review(documentation["id"], "lin")
        attach_check(self.p, doc_review, 129, 129)
        self.p.accept(doc_review["id"], "lin")
        (Path(self.a["workspace"]) / "checkout.py").write_text(PRICE.replace("129", "199"))
        newer = self.p.submit(self.a["id"], self.a["attempt"], handoff=True)

        # A1 is an ancestor, not the tip, and A2 must not replace its accepted bytes.
        update = self.p.prepare_update(delivery["id"])
        self.assertEqual(update["base"], doc_review["candidate_sha"])
        self.assertNotEqual(update["base"], newer["sha"])
        self.assertNotIn("onto_delivery_id", update)
        self.assertEqual((Path(update["workspace"]) / "checkout.py").read_text(), PRICE)
        self.assertEqual((Path(update["workspace"]) / "README.md").read_text(), "Accepted documentation\n")

    def test_accepted_dependency_does_not_bypass_self_dependency_guard(self):
        review = self.p.review(self.da["id"], "zhou")
        attach_check(self.p, review, 129, 129)
        self.p.accept(review["id"], "zhou")
        self.rejected("invalid_dependency", self.p.review, self.da["id"], "zhou", self.da["id"])
        self.rejected("invalid_dependency", self.p.prepare_update, self.da["id"], self.da["id"])

    def test_dependency_cycle_is_rejected(self):
        _, delivery = self.repair()
        self.rejected("invalid_dependency", self.p.prepare_update, self.da["id"], delivery["id"])
        self.assert_team_unchanged()

    def test_dependency_ancestry_git_failure_is_not_ignored(self):
        original_git = self.p._git

        def fail_ancestry(*args, **kwargs):
            if args[0] == "merge-base":
                raise PrototypeError("git_error", "Cannot read dependency object")
            return original_git(*args, **kwargs)

        with patch.object(self.p, "_git", side_effect=fail_ancestry):
            self.rejected("git_error", self.p.prepare_update, self.db["id"], self.da["id"])
        self.assertEqual(next(w for w in self.p.status()["workings"] if w["id"] == self.b["id"])["attempt"], 1)
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
