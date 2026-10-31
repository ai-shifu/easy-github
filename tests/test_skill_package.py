import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from package_skill import build


class PortableSkillTests(unittest.TestCase):
    def test_relocated_archive_runs_handoff_without_development_checkout(self):
        with tempfile.TemporaryDirectory(prefix="easy-github-package-") as directory:
            root = Path(directory)
            archive = root / "release.skill"
            result = build(archive)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(root / "unpacked")
            skill = root / "installed elsewhere" / "renamed skill"
            skill.parent.mkdir()
            (root / "unpacked" / "easy-github").rename(skill)
            manifest = json.loads((skill / "manifest.json").read_text())
            for name, expected in manifest["files_sha256"].items():
                self.assertEqual(hashlib.sha256((skill / name).read_bytes()).hexdigest(), expected)
            self.assertEqual(result["files"], len(manifest["files_sha256"]) + 1)

            # Readers must be able to follow either language's documentation
            # after installing the archive without the development checkout.
            for document in skill.rglob("*.md"):
                for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                    if "://" in target or target.startswith("#"):
                        continue
                    linked = (document.parent / target.split("#", 1)[0]).resolve()
                    self.assertIn(skill.resolve(), linked.parents, (document, target))
                    self.assertTrue(linked.is_file(), (document, target))

            source = root / "source project café 项目"
            source.mkdir()
            state = root / "working state"
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

            def git(*args, cwd=source):
                return subprocess.run(["git", *args], cwd=cwd, env=env, text=True,
                                      capture_output=True, check=True).stdout.strip()

            def command(script, *args, success=True, environment=env):
                call = subprocess.run([sys.executable, str(skill / "scripts" / script), *args],
                                      cwd=root, env=environment, text=True, capture_output=True)
                self.assertEqual(call.returncode == 0, success, call.stdout + call.stderr)
                return json.loads(call.stdout)

            def manage(*args, success=True):
                return command("newgit.py", "--state", str(state), *args, success=success)

            git("init", "-b", "main")
            git("config", "user.name", "Packaging Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("config", "core.hooksPath", "/dev/null")
            (source / "price.py").write_text("price = 99\n")
            git("add", "price.py")
            git("commit", "-m", "Fixture baseline")
            baseline = git("rev-parse", "HEAD")
            original = manage("init", "--source", str(source))
            self.assertEqual(original["team_sha"], baseline)
            title = "Update price · 调价 · تحديث السعر"
            work = manage("start", "--owner", "alice", "--tool", "fixture", "--title", title)
            (Path(work["workspace"]) / "price.py").write_text("price = 129\n")
            delivery = manage("submit", "--work", work["id"], "--attempt", "1",
                              "--handoff", "--summary", "Packaging fixture, not real AI")
            review = manage("review", "--delivery", delivery["id"], "--reviewer", "bob")
            self.assertEqual(review["status"], "ready")
            candidate = review["candidate_sha"]
            candidate_code = git("--git-dir", str(state / "repo.git"), "show", candidate + ":price.py")
            self.assertEqual(candidate_code, "price = 129")
            rejected = manage("check", "--review", review["id"], "--snapshot", baseline,
                              "--name", "fixture", "--status", "passed", success=False)
            self.assertEqual(rejected["error"]["code"], "wrong_snapshot")
            manage("check", "--review", review["id"], "--snapshot", candidate,
                   "--name", "fixture-snapshot", "--status", "passed",
                   "--detail", "Read exact candidate price.py; value is 129")
            status = manage("status")
            self.assertEqual(status["workings"][0]["title"], title)
            self.assertEqual(status["team_sha"], baseline)
            self.assertEqual(git("rev-parse", "main"), baseline)
            self.assertEqual((source / "price.py").read_text(), "price = 99\n")

            # The portable GitHub entrypoint rejects main before any gh invocation.
            delivery_file, body_file = root / "delivery.json", root / "body.md"
            delivery_file.write_text(json.dumps(delivery))
            body_file.write_text("Fixture only")
            denied = command("github_live.py", "--repository", "fixture/newgit-integration-portable",
                             "--git-dir", str(state / "repo.git"), "--evidence-dir", str(root / "evidence"),
                             "publish", "--delivery-file", str(delivery_file), "--title", "Fixture",
                             "--body-file", str(body_file), "--base", "main", success=False,
                             environment={**env, "PATH": ""})
            self.assertEqual(denied["error"], "invalid_branch")
            self.assertFalse((root / "evidence").exists())
            cli = subprocess.run([sys.executable, str(skill / "scripts/coders.py"), "--help"],
                                 cwd=root, capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)


if __name__ == "__main__":
    unittest.main()
