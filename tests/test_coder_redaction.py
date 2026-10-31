import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "prototype"), str(ROOT / "scripts")]
from coders import redactor, run
from demo_support import seed_project


class CredentialEvidenceTests(unittest.TestCase):
    def test_structured_key_spelling_variants_are_redacted(self):
        cleaned = redactor()({"apiKey": "private-value", "x-api-key": "private-value",
                              "nested": [{"clientSecret": "private-value"}],
                              "api_key_source": "native-settings"})
        self.assertNotIn("private-value", json.dumps(cleaned))
        self.assertEqual(cleaned["api_key_source"], "native-settings")

    def test_native_plain_text_credentials_never_reach_evidence(self):
        secrets = ["provider-key-from-native-config", "YmFzaWMtZml4dHVyZS1zZWNyZXQ=",
                   "project-key-from-native-config", "sk-proj-fixture-only-1234567890"]
        lines = ["x-api-key: " + secrets[0], "Authorization: Basic " + secrets[1],
                 'apiKey="' + secrets[2] + '"', secrets[3]]
        with tempfile.TemporaryDirectory(prefix="coder-private-evidence-") as directory:
            root = Path(directory)
            workspace = seed_project(root)
            prompt = root / "prompt.txt"
            prompt.write_text(lines[0])
            child = root / "child.py"
            child.write_text(
                "import json,sys\nsys.stdin.read()\n"
                + "text=" + repr("\n".join(lines)) + "\n"
                + "print(text,file=sys.stderr)\n"
                + "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))\n"
                + "print(json.dumps({'type':'turn.completed'}))\n")
            output = root / "evidence"
            with patch("coders.command_for", return_value=[sys.executable, str(child)]):
                result = run("codex", workspace, prompt, output)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            for path in output.iterdir():
                for secret in secrets:
                    self.assertNotIn(secret, path.read_text(), path.name)


if __name__ == "__main__":
    unittest.main()
