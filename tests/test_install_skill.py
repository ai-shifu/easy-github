import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from install_skill import InstallError, destination_for, install


class SkillInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="easy-github-installer-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "installed" / "easy-github"
        self.source.mkdir()
        (self.source / "scripts").mkdir()
        self.contents = {"SKILL.md": b"Fixture skill\n", "scripts/runner.py": b"print('fixture')\n"}
        for name, data in self.contents.items():
            (self.source / name).write_bytes(data)
        self.manifest = {
            "name": "easy-github", "version": "0.1.2",
            "files_sha256": {name: hashlib.sha256(data).hexdigest()
                             for name, data in self.contents.items()},
        }
        self.save_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def save_manifest(self):
        (self.source / "manifest.json").write_text(json.dumps(self.manifest))

    def test_install_and_repeat_only_copy_manifest_files(self):
        (self.source / "unlisted-local.env").write_text("fixture-private-setting")
        result = install(self.source, self.destination)
        self.assertEqual(result["status"], "installed")
        self.assertEqual(result["version"], "0.1.2")
        self.assertEqual(Path(result["path"]), self.destination)
        for name, data in self.contents.items():
            self.assertEqual((self.destination / name).read_bytes(), data)
        self.assertFalse((self.destination / "unlisted-local.env").exists())
        before = {p: p.stat().st_mtime_ns for p in self.destination.rglob("*")}
        self.assertEqual(install(self.source, self.destination)["status"], "unchanged")
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.destination.rglob("*")})

    def test_user_changes_are_not_overwritten(self):
        install(self.source, self.destination)
        (self.destination / "SKILL.md").write_text("User customization")
        with self.assertRaises(InstallError):
            install(self.source, self.destination)
        self.assertEqual((self.destination / "SKILL.md").read_text(), "User customization")

    def test_additional_destination_files_are_preserved_and_refused(self):
        install(self.source, self.destination)
        (self.destination / "notes.txt").write_text("User notes")
        with self.assertRaises(InstallError):
            install(self.source, self.destination)
        self.assertEqual((self.destination / "notes.txt").read_text(), "User notes")

    def test_hash_failure_prevents_destination_creation(self):
        (self.source / "scripts/runner.py").write_text("modified payload")
        with self.assertRaises(InstallError):
            install(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_bad_manifest_identity_or_version_is_refused(self):
        for key, value in [("name", "another-skill"), ("version", ""), ("version", None)]:
            with self.subTest(key=key, value=value):
                original = self.manifest[key]
                self.manifest[key] = value
                self.save_manifest()
                with self.assertRaises(InstallError):
                    install(self.source, self.destination)
                self.assertFalse(self.destination.exists())
                self.manifest[key] = original

    def test_malicious_paths_are_rejected_without_writes(self):
        for name in ["../outside", "/outside", "C:/outside", "scripts/../outside", "./SKILL.md", "x\\outside", "manifest.json"]:
            with self.subTest(name=name):
                self.manifest["files_sha256"][name] = "0" * 64
                self.save_manifest()
                with self.assertRaises(InstallError):
                    install(self.source, self.destination)
                self.assertFalse(self.destination.exists())
                del self.manifest["files_sha256"][name]

    def test_source_file_and_directory_symlinks_are_rejected(self):
        original = self.source / "scripts/runner.py"
        external = self.root / "external.py"
        external.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(external)
        with self.assertRaises(InstallError):
            install(self.source, self.destination)
        original.unlink()
        original.write_bytes(external.read_bytes())
        real_directory = self.root / "real-scripts"
        (self.source / "scripts").rename(real_directory)
        (self.source / "scripts").symlink_to(real_directory, target_is_directory=True)
        with self.assertRaises(InstallError):
            install(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_destination_symlink_is_not_followed(self):
        install(self.source, self.destination)
        alias = self.root / "alias"
        alias.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(InstallError):
            install(self.source, alias)
        self.assertEqual((self.destination / "SKILL.md").read_bytes(), self.contents["SKILL.md"])

    def test_destination_selection_uses_codex_home_without_mutation(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root / "custom-codex")}):
            self.assertEqual(destination_for(), self.root / "custom-codex/skills/easy-github")
            self.assertEqual(destination_for("codex"), destination_for())
        self.assertEqual(destination_for("claude"), Path.home() / ".claude/skills/easy-github")
        self.assertEqual(destination_for(dest=self.destination), self.destination)
        with self.assertRaises(InstallError):
            destination_for(target="codex", dest=self.destination)
        with self.assertRaises(InstallError):
            destination_for(dest="relative-directory")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
