# Install Easy GitHub

[English](installation.md) | [简体中文](zh-CN/installation.md)

Easy GitHub v0.1.3 is a self-contained Skill with instructions and Python runtime scripts. Installing the Skill does not install, authenticate, or upgrade coding tools, or automatically connect a GitHub repository.

## Requirements

| Usage | Requirements |
|---|---|
| Local code management | macOS/Linux, Python 3.11 or newer, Git, and a local Git project with at least one commit |
| Using the Skill in an AI tool | A tool that supports local Skills, such as Codex or Claude Code |
| Optional external CLI runner | The Codex, Claude Code, or Copilot CLI you want to invoke, already installed and working |
| GitHub test-repository integration | An authenticated `gh` CLI and a target test repository that meets the adapter's restrictions |

The program uses `fcntl` for state locking and does not support native Windows. No additional Python runtime dependencies are required. CI tests Python 3.11 and 3.13. Use a UTF-8 terminal and locale so non-ASCII paths and arguments are passed correctly.

## Install from the repository

Clone the default `main` branch:

```bash
git clone https://github.com/ai-shifu/easy-github.git
cd easy-github
```

### Codex

```bash
python3 scripts/install_skill.py --target codex
```

The default destination is `~/.codex/skills/easy-github/`. If `CODEX_HOME` is set, the installer uses its `skills/easy-github/` directory instead. The installer reports the actual destination.

Invoke `$easy-github` in Codex:

```text
Use $easy-github to check this project's code collaboration state. Do not change application code yet.
```

### Claude Code

```bash
python3 scripts/install_skill.py --target claude
```

The destination is `~/.claude/skills/easy-github/`. In Claude Code, use:

```text
/easy-github Help me prepare an isolated workspace for this change.
```

See the [official Claude Code documentation](https://code.claude.com/docs/en/skills) for its Skill location and invocation syntax. The Skill can manage work directly inside Claude Code. Authentication and availability of the optional runner still depend on your local environment.

### Custom directory

`--dest` specifies the final Skill directory, not its parent:

```bash
python3 scripts/install_skill.py --dest /absolute/path/to/skills/easy-github
```

For another tool that supports Skills, first check its installation directory and invocation syntax. Support for launching a coding CLI through the runner does not mean its native Skill has been installed.

The installer validates the packaged files. If the destination already contains an identical installation, it makes no changes. If the contents differ, it stops to avoid overwriting your edits. Before upgrading, back up or move the old installation, then install the new version. Keep project state and workspaces outside the installation directory; do not overwrite or relocate them with the Skill.

## Install the archive manually

The repository provides [dist/easy-github.skill](../dist/easy-github.skill). It is a ZIP archive with a single top-level `easy-github/` folder.

1. Download and extract the archive. If your archive tool does not recognize the extension, rename a copy to `.zip` first.
2. Copy the entire `easy-github/` folder into your tool's Skills directory.
3. Confirm that it contains `SKILL.md`, `scripts/`, `references/`, `manifest.json`, and `LICENSE`.

Do not copy only `SKILL.md`, or place an existing project's state repository, logs, or credentials inside the Skill directory.

## Verify the installation

From the Skill directory reported by the installer, run these commands to check that the scripts start:

```bash
python3 scripts/newgit.py --help
python3 scripts/coders.py --help
python3 scripts/github_live.py --help
```

These commands display help only; they do not initialize a project or operate on GitHub. If your tool has not listed the new Skill, reopen the session or use the tool's supported method to load `SKILL.md` directly from the installation directory.

When starting real work, tell the AI where the source project is and where any existing state directory lives. Initialization reads only the source project's committed HEAD. Reuse the original state directory when continuing work. See the [local workflow](../skills/easy-github/references/workflow.md) for details.

## Uninstall

Once you no longer need the installation, delete the `easy-github/` folder reported by the installer. Do not delete project state directories or their workspaces. Uninstalling the Skill does not mean those changes have been accepted or backed up.
