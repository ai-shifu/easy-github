import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype"))
from coders import run


class CoderTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="newgit-timeout-test-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Fixture task")

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, code, *, timeout=1, label="out"):
        script = self.root / (label + ".py")
        script.write_text(code)
        with patch("coders.command_for", return_value=[sys.executable, "-u", str(script)]):
            return run("codex", self.workspace, self.prompt, self.root / label, timeout=timeout)

    def lingering_child(self, pipe, detached=False):
        pid_file = self.root / (pipe + "-pid.txt")
        heartbeat = self.root / (pipe + "-heartbeat.txt")
        child = (
            "import os,signal,time\nfrom pathlib import Path\n"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
            "end=time.monotonic()+8\n"
            "while time.monotonic()<end:\n"
            f" Path({str(heartbeat)!r}).write_text(str(time.monotonic()))\n"
            " time.sleep(.02)\n"
        )
        code = (
            "import json,subprocess,sys,time\nfrom pathlib import Path\nsys.stdin.read()\n"
            f"subprocess.Popen([sys.executable,'-c',{child!r}],"
            f"stdout={'None' if pipe == 'stdout' else 'subprocess.DEVNULL'},"
            f"stderr={'None' if pipe == 'stderr' else 'subprocess.DEVNULL'},"
            f"start_new_session={detached!r})\n"
            f"while not Path({str(pid_file)!r}).exists(): time.sleep(.005)\n"
            "print(json.dumps({'type':'turn.completed'}),flush=True)\n"
        )
        try:
            result = self.invoke(code, label=pipe)
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["failure_reason"], "output_drain_timeout")
            self.assertLess(result["duration_seconds"], 3)
            if not detached:
                previous = heartbeat.read_text()
                time.sleep(0.15)
                self.assertEqual(heartbeat.read_text(), previous, "Process-group child is still running")
            return result
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_deadline_covers_stdout_and_stderr_after_parent_exits(self):
        for pipe in ("stdout", "stderr"):
            with self.subTest(pipe=pipe):
                self.lingering_child(pipe)

    def test_escaped_pipe_holder_cannot_make_output_drain_unbounded(self):
        # The fixture owns and cleans this intentionally detached child. The
        # runner must close its pipe instead of waiting for an unreachable EOF.
        self.lingering_child("stdout", detached=True)

    def test_large_prompt_does_not_bypass_timeout_when_cli_ignores_stdin(self):
        self.prompt.write_text("x" * (1024 * 1024))
        code = "import json,time\nprint(json.dumps({'type':'turn.completed'}),flush=True)\ntime.sleep(8)\n"
        result = self.invoke(code)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["timed_out"])
        self.assertLess(result["duration_seconds"], 3)

    def test_split_utf8_and_unterminated_final_lines_are_preserved_and_redacted(self):
        secret = "fixture-only-drain-secret-987654321"
        message = json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "检查完成 " + secret}}, ensure_ascii=False) + "\n"
        message += json.dumps({"type": "turn.completed"})
        code = (
            "import os,sys,time\nsys.stdin.read()\n"
            f"for value in {message.encode('utf-8')!r}:\n"
            " os.write(1,bytes([value]))\n time.sleep(.0002)\n"
            f"os.write(2,{'Bearer ' + secret!r}.encode())\n"
        )
        with patch.dict(os.environ, {"NEWGIT_DRAIN_TEST_SECRET": secret}):
            result = self.invoke(code, timeout=3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["event_count"], 2)
        self.assertEqual((self.root / "out/final.txt").read_text(), "检查完成 [redacted]")
        self.assertEqual((self.root / "out/stderr.txt").read_text(), "Bearer [redacted]")
        for path in (self.root / "out").iterdir():
            self.assertNotIn(secret, path.read_text())


if __name__ == "__main__":
    unittest.main()
