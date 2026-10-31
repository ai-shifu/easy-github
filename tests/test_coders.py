import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "prototype"), str(ROOT / "scripts")]
from coders import copilot_mcp_names, run
from demo_support import seed_project


class CoderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="newgit-coder-test-")
        self.root = Path(self.tmp.name)
        self.workspace = seed_project(self.root)
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Fixture task")

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, code):
        script = self.root / "fake.py"
        script.write_text(code)
        return patch("coders.command_for", return_value=[sys.executable, "-u", str(script)])

    def test_output_credentials_are_redacted_before_evidence_is_kept(self):
        secret = "fixture-only-secret-123456789"
        code = """import json,os,sys
sys.stdin.read()
s=os.environ['NEWGIT_TEST_SECRET']
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':s}}))
print('Bearer '+s,file=sys.stderr)
print(json.dumps({'type':'turn.completed','access_token':s}))
"""
        with self.fake(code), patch.dict(os.environ, {"NEWGIT_TEST_SECRET": secret}):
            result = run("codex", self.workspace, self.prompt, self.root / "out")
        self.assertEqual(result["status"], "completed")
        for file in (self.root / "out").iterdir():
            self.assertNotIn(secret, file.read_text())
        self.assertIn("[redacted]", (self.root / "out/final.txt").read_text())

    def test_review_detects_source_mutation_even_if_cli_reports_success(self):
        code = """import json,sys
from pathlib import Path
sys.stdin.read()
Path('checkout.py').write_text('unexpected edit')
print(json.dumps({'type':'turn.completed'}))
"""
        with self.fake(code):
            result = run("codex", self.workspace, self.prompt, self.root / "out", mode="review")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "review_workspace_changed")

    def test_authentication_retry_stops_without_waiting_for_full_timeout(self):
        code = """import json,sys,time
sys.stdin.read()
for _ in range(2):
 print(json.dumps({'type':'system','subtype':'api_retry','error':'authentication_failed'}),flush=True)
time.sleep(60)
"""
        with self.fake(code):
            result = run("claude", self.workspace, self.prompt, self.root / "out", timeout=10)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "authentication_failed")
        self.assertLess(result["duration_seconds"], 5)

    def test_copilot_accepts_plain_text_and_does_not_inherit_allow_all(self):
        code = """import os,sys
assert 'COPILOT_ALLOW_ALL' not in os.environ
assert sys.stdin.read() == 'Fixture task'
print('Implemented fixture changes; independent checks are still required.')
"""
        with self.fake(code), patch.dict(os.environ, {"COPILOT_ALLOW_ALL": "true"}):
            result = run("copilot", self.workspace, self.prompt, self.root / "out")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output_format"], "plain_text")
        self.assertEqual(result["event_count"], 0)
        self.assertIsNone(result["session_id"])
        self.assertIn("CLI completion only", result["success_scope"])
        self.assertIn("independent checks", (self.root / "out/final.txt").read_text())
        self.assertFalse((self.root / "out/events.jsonl").exists())
        self.assertNotIn("Fixture task", (self.root / "out/manifest.json").read_text())

    def test_copilot_rejects_empty_or_failed_response(self):
        for label, code in [
            ("empty", "import sys; sys.stdin.read()"),
            ("failed", "import sys; sys.stdin.read(); print('Partial result'); sys.exit(1)"),
        ]:
            with self.subTest(label=label), self.fake(code):
                result = run("copilot", self.workspace, self.prompt, self.root / label)
            self.assertEqual(result["status"], "failed")

    def test_copilot_authentication_failure_does_not_wait_for_timeout(self):
        code = """import sys,time
sys.stdin.read()
print('Error: No authentication information found.', file=sys.stderr, flush=True)
time.sleep(60)
"""
        with self.fake(code):
            result = run("copilot", self.workspace, self.prompt, self.root / "out", timeout=10)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "authentication_failed")
        self.assertLess(result["duration_seconds"], 5)

    def test_copilot_review_is_rejected_if_clean_checkout_changes(self):
        code = """import sys
from pathlib import Path
sys.stdin.read()
Path('checkout.py').write_text('unexpected edit')
print('No blocking findings')
"""
        with self.fake(code):
            result = run("copilot", self.workspace, self.prompt, self.root / "out", mode="review")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "review_workspace_changed")

    def test_copilot_plain_text_is_redacted_before_evidence_is_kept(self):
        secret = "fixture-only-secret-123456789"
        code = """import os,sys
sys.stdin.read()
print('Result '+os.environ['NEWGIT_TEST_SECRET'])
print('Bearer '+os.environ['NEWGIT_TEST_SECRET'], file=sys.stderr)
"""
        with self.fake(code), patch.dict(os.environ, {"NEWGIT_TEST_SECRET": secret}):
            result = run("copilot", self.workspace, self.prompt, self.root / "out")
        self.assertEqual(result["status"], "completed")
        for file in (self.root / "out").iterdir():
            self.assertNotIn(secret, file.read_text())
        self.assertIn("[redacted]", (self.root / "out/final.txt").read_text())

    def test_copilot_config_returns_only_server_names(self):
        config = self.root / "mcp-config.json"
        config.write_text(json.dumps({"mcpServers": {
            "example": {"command": "private-command", "env": {"TOKEN": "private-token"}},
            "another": {"url": "https://private.example"},
        }}))
        self.assertEqual(copilot_mcp_names(config), ["another", "example"])

    def test_copilot_rejects_unreadable_mcp_configuration(self):
        config = self.root / "mcp-config.json"
        for value in ["{broken", '{"mcpServers": []}', '{"mcpServers":{"invalid name":{}}}']:
            config.write_text(value)
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Cannot safely enumerate"):
                    copilot_mcp_names(config)

    def test_invalid_config_does_not_claim_output_path_and_retry_succeeds(self):
        output = self.root / "retry-output"
        with patch("coders.copilot_mcp_names", side_effect=ValueError("Cannot safely enumerate")):
            with self.assertRaisesRegex(ValueError, "Cannot safely enumerate"):
                run("copilot", self.workspace, self.prompt, output)
        self.assertFalse(output.exists())
        with self.fake("import sys; sys.stdin.read(); print('Completed fixture')"):
            result = run("copilot", self.workspace, self.prompt, output)
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
