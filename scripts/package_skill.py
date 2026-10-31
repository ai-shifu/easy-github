#!/usr/bin/env python3
"""Build the self-contained Easy GitHub skill from explicit, reviewed files.

Run from any directory. Development sources remain in prototype/; only the
three runtime modules are copied into the skill. No state, logs, or credentials
are collected. The resulting .skill file is a ZIP with one top-level folder.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NAME = "easy-github"
VERSION = "0.1.2"
RUNTIMES = ("newgit.py", "coders.py", "github_live.py")
STATIC = (
    "SKILL.md", "LICENSE", "agents/openai.yaml", "references/workflow.md",
    "references/coders.md", "references/github.md",
)


def build(output=None):
    skill = ROOT / "skills" / NAME
    # Validate all inputs before modifying generated runtime copies or a bundle.
    inputs = {name: skill / name for name in STATIC}
    inputs.update({"scripts/" + name: ROOT / "prototype" / name for name in RUNTIMES})
    for name, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError("Expected a regular package input: " + name)
    payloads = {name: path.read_bytes() for name, path in inputs.items()}
    for name in RUNTIMES:
        target = skill / "scripts" / name
        if target.is_symlink():
            raise ValueError("Refusing symlink runtime destination: " + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads["scripts/" + name])
    manifest = {
        "name": NAME, "version": VERSION,
        "files_sha256": {name: hashlib.sha256(data).hexdigest()
                         for name, data in sorted(payloads.items())},
        "runtime_source": "Development sources live in prototype/; rebuild with scripts/package_skill.py.",
    }
    payloads["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    (skill / "manifest.json").write_bytes(payloads["manifest.json"])
    output = Path(output) if output is not None else ROOT / "dist" / (NAME + ".skill")
    if output.is_symlink():
        raise ValueError("Refusing symlink archive destination")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Explicit inputs and stable metadata make repeated builds byte-identical.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payloads.items()):
            info = zipfile.ZipInfo(NAME + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive integrity verification failed")
    return {"name": NAME, "version": VERSION, "skill_directory": str(skill),
            "archive": str(output.resolve()), "files": len(payloads),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
