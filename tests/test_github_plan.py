from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))
from github_plan import publish_plan, bind_pr_readback, ContractError


class UpdatePlanTests(unittest.TestCase):
    def test_existing_pr_updates_metadata_before_exact_readback(self):
        delivery = {"work_id": "coupon", "sha": "b" * 40, "revision": 2}
        plan = publish_plan("example/project", delivery, "Preserve new price and add coupon",
                            base="newgit/price", previous_head="a" * 40, pull_number=7)
        push, update, readback = plan["steps"]
        self.assertEqual(push["expected_old_sha"], "a" * 40)
        self.assertEqual((update["method"], update["path"]),
                         ("PATCH", "/repos/example/project/pulls/7"))
        self.assertEqual(update["body"]["title"], "Preserve new price and add coupon")
        self.assertEqual(update["body"]["base"], "newgit/price")
        self.assertIn("revision 2", update["body"]["body"])
        self.assertIn(delivery["sha"], update["body"]["body"])
        self.assertEqual(readback["method"], "GET")
        response = {"number": 7, "state": "open", "draft": False, "merged": False,
                    "head": {"sha": delivery["sha"], "ref": "newgit/coupon"},
                    "base": {"ref": "newgit/price", "repo": {"full_name": "example/project"}}}
        self.assertEqual(bind_pr_readback(plan, response)["pull_number"], 7)
        response["base"]["ref"] = "prototype-team"
        with self.assertRaises(ContractError):
            bind_pr_readback(plan, response)


if __name__ == "__main__":
    unittest.main()
