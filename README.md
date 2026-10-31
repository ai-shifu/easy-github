# Easy GitHub

[English](README.md) | [简体中文](README.zh-CN.md)

**Manage code collaboration in natural language, so people can focus on direction and review.**

A friendlier GitHub workflow for humans and AI coding tools.

Easy GitHub is a Skill for teams working with multiple people and AI coding tools. Your chosen coding tools write the code. Easy GitHub prepares isolated workspaces, freezes deliveries, assembles review materials, and hands context back to those tools when changes need revisions before they can work together.

**Current version: 0.1.3, prototype.** The local workflow works with local Git projects. GitHub writes are currently limited to private `newgit-integration-*` test repositories. Easy GitHub never proactively merges into `main` or treats an AI review as human approval.

## Quick installation

You need macOS or Linux, Python 3.11 or newer, and Git. Use a UTF-8 terminal and locale for non-ASCII paths and arguments. Clone the repository's default `main` branch:

```bash
git clone https://github.com/ai-shifu/easy-github.git
cd easy-github
python3 scripts/install_skill.py --target codex
```

Then invoke the Skill in Codex:

```text
Use $easy-github to prepare an isolated workspace for this task. I'll use Codex to write the code.
```

Claude Code users can install with `--target claude` and invoke `/easy-github`. The installer refuses to overwrite an existing Skill with different contents. Reinstalling identical contents does not rewrite files.

The [installation guide](docs/installation.md) covers custom directories, archive installation, and verification.

## How to use it

Describe what you want to do in your preferred language:

```text
Use $easy-github to hand off these changes and prepare them for a colleague to review.

Use $easy-github to check whether these two deliveries can work together.
Neither has been accepted yet. If revisions are needed, prepare a new workspace and keep the old versions.

Use $easy-github to send this version to the specified test repository for review. Do not merge it yet.
```

The Skill keeps Git / GitHub versions, diffs, and PR links visible so you can understand the current state. You do not need to arrange branches manually or memorize commit commands first.

See the [usage examples](docs/examples.md) for a complete walkthrough.

## What it can do today

| Capability | Current behavior |
|---|---|
| Isolated work | Prepare a separate workspace for each task and coding tool |
| Frozen deliveries | Save an immutable delivery after external tools stop writing |
| Combination checks and conflict context | Check two deliveries, preserve old workspaces, and prepare a new revision workspace and context for an external AI tool |
| Review and check records | Bind diffs, checks, and reviews to a specific version |
| Optional tool invocation | Run an installed, authenticated Codex, Claude Code, or GitHub Copilot CLI |
| Test-repository PRs | Publish frozen deliveries, create or update PRs, and post AI `COMMENT` reviews bound to a version |

See [SKILL.md](skills/easy-github/SKILL.md) for responsibilities, commands, and integration details.

## Current limits

- **The state repository is a separate copy.** Initialization imports only the source project's committed HEAD. It does not subsequently synchronize with the source project or a remote. Uncommitted changes do not automatically enter new workspaces.
- **Local acceptance updates only the state repository.** It does not update the source project or GitHub. A combination preview cannot be accepted directly.
- **The GitHub adapter is experimental.** It only targets private `newgit-integration-*` repositories on `github.com`, with an existing target baseline. It does not create repositories or provide merge or `APPROVE` operations. Easy GitHub itself is a public, open-source project.
- **People still make the decisions.** `ready` means ready for review. Passing CI, AI recommendations, and human approval are different states. Local participant names are labels, not authenticated identities.
- **There is no full product interface yet.** There is no GUI, background autosave, automatic remote synchronization, or full multi-user permission system. State directories contain machine-specific paths and cannot be relocated with the Skill.

The tool allowlist is not an operating-system sandbox. See [coding tool integration](skills/easy-github/references/coders.md) for external tool permissions and what is actually checked.

## Development and verification

The Python runtime uses only the standard library. Run the local tests:

```bash
python3 -m unittest discover -s tests -v
```

The local demo uses simulated participants and temporary Git repositories. It does not call real models or GitHub:

```bash
python3 scripts/run_demo.py
```

After changing runtime sources in `prototype/`, regenerate the Skill's script copies and archive:

```bash
python3 scripts/package_skill.py
```

Do not maintain separate implementations in `prototype/` and the Skill's runtime scripts. The generated `manifest.json` records hashes of packaged files. Packaging excludes runtime state, credentials, and machine-local logs.

See the [contribution guide](CONTRIBUTING.md) for the review workflow and language conventions.

## License

[MIT](LICENSE). The Skill archive includes the license and may be used, modified, and distributed under its terms.
