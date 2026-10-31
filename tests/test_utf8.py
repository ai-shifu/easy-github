import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Utf8BoundaryTests(unittest.TestCase):
    def run_in_c_locale(self, code, directory):
        # Keep argv and paths ASCII. Non-ASCII data is introduced inside Python;
        # this tests our text boundaries, not the interpreter's argv decoding.
        code = textwrap.dedent(code)
        self.assertTrue(code.isascii())
        self.assertTrue(str(directory).isascii())
        environment = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0",
                       "PYTHONCOERCECLOCALE": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        environment.pop("PYTHONIOENCODING", None)
        result = subprocess.run([sys.executable, "-c", code, str(directory)], cwd=ROOT,
                                env=environment, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_state_delivery_diff_and_cli_output_preserve_unicode_in_c_locale(self):
        with tempfile.TemporaryDirectory(prefix="easy-github-utf8-") as directory:
            result = self.run_in_c_locale(r'''
                import json, subprocess, sys
                from pathlib import Path
                before = (sys.stdout.encoding, sys.stderr.encoding)
                from prototype.newgit import Prototype
                assert (sys.stdout.encoding, sys.stderr.encoding) == before
                assert sys.flags.utf8_mode == 0
                root = Path(sys.argv[1])
                source = root / "source"
                source.mkdir()
                def git(*args):
                    return subprocess.run(["git", "-C", str(source), *args], check=True,
                                          capture_output=True, encoding="utf-8").stdout.strip()
                git("init", "-b", "main")
                git("config", "user.name", "Encoding Fixture")
                git("config", "user.email", "fixture@example.invalid")
                git("config", "commit.gpgsign", "false")
                git("config", "core.hooksPath", "/dev/null")
                (source / "note.txt").write_text("Original\n", encoding="utf-8")
                git("add", "note.txt")
                git("commit", "-m", "Initial fixture")
                baseline = git("rev-parse", "main")
                state = root / "state"
                manager = Prototype.initialize(source, state)
                message = "caf\u00e9 \u4ea4\u4ed8 \u0645\u0631\u062d\u0628\u0627"
                work = manager.start("alice", "fixture", message)
                (Path(work["workspace"]) / "note.txt").write_text(message + "\n", encoding="utf-8")
                delivery = manager.submit(work["id"], work["attempt"], message, handoff=True)
                review = manager.review(delivery["id"], "bob")
                assert review["status"] == "ready"
                assert message in review["diff"]
                assert message in manager._git("show", "-s", "--format=%B", delivery["sha"])
                saved = json.loads((state / "state.json").read_text(encoding="utf-8"))
                assert saved["works"][work["id"]]["title"] == message
                assert saved["deliveries"][delivery["id"]]["summary"] == message
                cli = subprocess.run([sys.executable, "prototype/newgit.py", "--state", str(state), "status"],
                                     check=True, capture_output=True, encoding="utf-8")
                assert json.loads(cli.stdout)["workings"][0]["title"] == message
                assert message in cli.stdout
                assert git("rev-parse", "main") == baseline
                sys.stdout.buffer.write(cli.stdout.encode("utf-8"))
            ''', directory)
            self.assertIn("café", result.stdout)

    def test_coding_runners_read_utf8_prompt_and_preserve_output_in_c_locale(self):
        with tempfile.TemporaryDirectory(prefix="easy-github-utf8-") as directory:
            result = self.run_in_c_locale(r'''
                import json, sys
                from pathlib import Path
                from unittest.mock import patch
                before = (sys.stdout.encoding, sys.stderr.encoding)
                from prototype import coders
                assert (sys.stdout.encoding, sys.stderr.encoding) == before
                root = Path(sys.argv[1])
                workspace = root / "workspace"
                workspace.mkdir()
                message = "caf\u00e9 \u68c0\u67e5\u5b8c\u6210"
                prompt = root / "prompt.txt"
                prompt.write_text(message, encoding="utf-8")
                config = root / "mcp-config.json"
                config.write_text(json.dumps({"mcpServers": {"fixture": {"description": message}}},
                                             ensure_ascii=False), encoding="utf-8")
                assert coders.copilot_mcp_names(config) == ["fixture"]
                fixture = root / "coder.py"
                fixture.write_text(
                    "import json,sys\n"
                    "message=sys.stdin.buffer.read().decode('utf-8')\n"
                    "tool=sys.argv[1]\n"
                    "if tool=='copilot':\n"
                    " sys.stdout.buffer.write(message.encode('utf-8'))\n"
                    "else:\n"
                    " events=[{'type':'item.completed','item':{'type':'agent_message','text':message}},"
                    "{'type':'turn.completed'},"
                    "{'type':'result','subtype':'success','is_error':False,'result':message,'session_id':message}]\n"
                    " for event in events:\n"
                    "  sys.stdout.buffer.write((json.dumps(event,ensure_ascii=False)+'\\n').encode('utf-8'))\n"
                    "sys.stderr.buffer.write(message.encode('utf-8'))\n", encoding="utf-8")
                for tool in ("codex", "claude", "copilot"):
                    output = root / tool
                    args = ["coders.py", "--tool", tool, "--workspace", str(workspace),
                            "--prompt-file", str(prompt), "--output", str(output)]
                    with patch.object(coders, "command_for", return_value=[sys.executable, str(fixture), tool]), \
                         patch.object(sys, "argv", args):
                        assert coders.main() == 0
                    assert (output / "prompt.txt").read_text(encoding="utf-8") == message
                    assert (output / "final.txt").read_text(encoding="utf-8").strip() == message
                    assert (output / "stderr.txt").read_text(encoding="utf-8") == message
                    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
                    assert manifest["status"] == "completed"
                    if tool == "claude":
                        assert manifest["session_id"] == message
            ''', directory)
            self.assertIn("café", result.stdout)

    def test_github_pipe_uses_utf8_without_changing_importers_streams(self):
        with tempfile.TemporaryDirectory(prefix="easy-github-utf8-") as directory:
            self.run_in_c_locale(r'''
                import sys
                from pathlib import Path
                before = (sys.stdout.encoding, sys.stderr.encoding)
                from prototype.github_live import GitHubReviewAdapter
                from scripts import install_skill, run_demo
                assert (sys.stdout.encoding, sys.stderr.encoding) == before
                root = Path(sys.argv[1])
                adapter = GitHubReviewAdapter("fixture/newgit-integration-utf8", root, root / "evidence")
                message = "caf\u00e9 \u5ba1\u67e5"
                result = adapter._run([sys.executable, "-c",
                    "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], input_text=message)
                assert result.returncode == 0
                assert result.stdout == message
            ''', directory)


if __name__ == "__main__":
    unittest.main()
