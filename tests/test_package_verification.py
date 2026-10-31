from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_skill


class TrackedPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="easy-github-package-check-")
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "skills/easy-github", self.root / "skills/easy-github")
        shutil.copytree(ROOT / "prototype", self.root / "prototype", ignore=shutil.ignore_patterns("__pycache__"))
        self.override = patch.object(package_skill, "ROOT", self.root)
        self.override.start()
        package_skill.build()
        self.archive = self.root / "dist/easy-github.skill"

    def tearDown(self):
        self.override.stop()
        self.tmp.cleanup()

    def rewrite(self, changes):
        with zipfile.ZipFile(self.archive) as old:
            contents = {name: old.read(name) for name in old.namelist()}
        contents.update(changes)
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as new:
            for name, content in contents.items():
                new.writestr(name, content)

    def test_stale_archive_is_rejected_without_overwriting_it(self):
        self.rewrite({"easy-github/scripts/newgit.py": b"old runtime"})
        before = self.archive.read_bytes()
        with self.assertRaisesRegex(ValueError, "Stale archive"):
            package_skill.verify()
        self.assertEqual(self.archive.read_bytes(), before)

    def test_same_contents_with_different_zip_encoding_pass(self):
        self.rewrite({})
        self.assertEqual(package_skill.verify()["status"], "verified")

    def test_extra_archive_files_are_rejected(self):
        self.rewrite({"easy-github/unexpected.txt": b"not part of distribution"})
        with self.assertRaisesRegex(ValueError, "file list"):
            package_skill.verify()


if __name__ == "__main__":
    unittest.main()
