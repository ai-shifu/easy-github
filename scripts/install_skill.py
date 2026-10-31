#!/usr/bin/env python3
"""Install the bundled Easy GitHub skill without overwriting existing work."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys


NAME = "easy-github"
SOURCE = Path(__file__).resolve().parents[1] / "skills" / NAME


class InstallError(ValueError):
    pass


def _payloads(source):
    source = Path(source)
    manifest_path = source / "manifest.json"
    if (source.is_symlink() or not source.is_dir() or manifest_path.is_symlink()
            or not manifest_path.is_file()):
        raise InstallError("The skill source and manifest must be regular files/directories, not symlinks.")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError) as error:
        raise InstallError("Cannot read a valid skill manifest.") from error
    if not isinstance(manifest, dict) or manifest.get("name") != NAME:
        raise InstallError("The manifest must identify easy-github.")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version):
        raise InstallError("The manifest must contain a valid version.")
    hashes = manifest.get("files_sha256")
    if not isinstance(hashes, dict) or "SKILL.md" not in hashes:
        raise InstallError("The manifest must list SKILL.md and file hashes.")
    payloads = {"manifest.json": manifest_bytes}
    for name, expected in hashes.items():
        if not isinstance(name, str):
            raise InstallError("Invalid package path.")
        relative = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or relative.is_absolute() or ".." in relative.parts
                or name != relative.as_posix() or name == "manifest.json"):
            raise InstallError("Invalid package path: " + name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise InstallError("Invalid SHA-256 for: " + name)
        path = source
        for part in relative.parts:
            path /= part
            if path.is_symlink():
                raise InstallError("Package symlinks are not supported: " + name)
        if not path.is_file():
            raise InstallError("Package file is missing or not regular: " + name)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise InstallError("Package hash mismatch: " + name)
        payloads[name] = data
    return version, payloads


def destination_for(target=None, dest=None):
    if target is not None and dest is not None:
        raise InstallError("Use either --target or --dest, not both.")
    if dest is not None:
        destination = Path(dest).expanduser()
        if not destination.is_absolute():
            raise InstallError("--dest must be an absolute path to the complete skill directory.")
        return destination
    if target in (None, "codex"):
        codex_root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
        return codex_root.absolute() / "skills" / NAME
    if target == "claude":
        return Path.home() / ".claude" / "skills" / NAME
    raise InstallError("Unknown target: " + str(target))


def _matches(destination, payloads):
    if destination.is_symlink() or not destination.is_dir():
        return False
    expected_dirs = {str(parent) for name in payloads for parent in PurePosixPath(name).parents
                     if str(parent) != "."}
    found_files, found_dirs = set(), set()
    for path in destination.rglob("*"):
        name = path.relative_to(destination).as_posix()
        if path.is_symlink():
            return False
        if path.is_dir():
            found_dirs.add(name)
        elif path.is_file() and name in payloads and path.read_bytes() == payloads[name]:
            found_files.add(name)
        else:
            return False
    return found_files == set(payloads) and found_dirs == expected_dirs


def install(source=SOURCE, destination=None):
    version, payloads = _payloads(source)
    destination = Path(destination) if destination is not None else destination_for()
    destination = destination.expanduser().absolute()
    result = {"name": NAME, "version": version, "path": str(destination)}
    if destination.exists() or destination.is_symlink():
        if _matches(destination, payloads):
            return {**result, "status": "unchanged"}
        raise InstallError(
            "Destination already exists and differs from this package: " + str(destination)
            + ". Move it to a backup location, inspect the backup, then rerun. No existing files were overwritten.")
    # Validate and read the whole package before creating anything. Exclusive
    # directory/file creation also refuses another installer winning a race.
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    try:
        for name, data in payloads.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
        if not _matches(destination, payloads):
            raise OSError("Installed files did not match the package")
    except OSError as error:
        raise InstallError(
            "Installation did not finish. Partial files were retained at " + str(destination)
            + "; inspect and move that directory to a backup before retrying.") from error
    return {**result, "status": "installed"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--target", choices=["codex", "claude"],
                             help="Skill host (default: codex)")
    destination.add_argument("--dest", type=Path,
                             help="Absolute path to a custom skill directory")
    args = parser.parse_args()
    try:
        result = install(destination=destination_for(args.target, args.dest))
    except (InstallError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
