---
name: easy-github
license: MIT
description: Manage code handoffs across people and AI coding tools using natural language. Use for starting isolated work, freezing deliveries, checking whether changes combine, preparing conflict repair and review, or publishing test PRs. Business coding stays with the user's chosen tool; GitHub writes currently support private test repositories only.
---

# Easy GitHub

English | [简体中文](references/zh-CN/skill.md)

Make GitHub easier to use: AI tools deliver changes, people review outcomes, and the program maintains versions and handoff records. Build on Git and GitHub while keeping the user's choice of coding tool.

Communicate in the user's language. English is the maintained source for these instructions, not a required conversation language. Preserve commands, status fields, IDs, paths, and user content as supplied; do not translate machine identifiers. Read the relevant reference only when its workflow is needed. Simplified Chinese translations are linked from each reference.

## Identify the work

Use the current context to identify the source repository, existing state directory, participants, and requested operation. Prefer continuing existing work. When there is enough information, act without requiring the user to learn branches, commits, or PR commands.

This Skill includes its runtime scripts. Resolve the Skill root from **the directory containing this SKILL.md**, and invoke `scripts/` with absolute paths; the development repository is not required. Keep runtime state, workspaces, and evidence outside the installation directory. Requirements are Python 3.11+, Git, and macOS/Linux with a UTF-8 terminal/locale for non-ASCII paths and arguments; native coding CLIs and GitHub are optional integrations.

For first use or command details, read the [local workflow](references/workflow.md). Inspect the source HEAD, uncommitted changes, and existing state before initializing. Initialization imports only committed HEAD. Keep state outside the source repository, for example in a sibling `<project>.handoff` directory. Verify an existing directory's ownership before reusing it; do not recreate or overwrite it. The state store has its own team version and does not automatically follow the source repository or a remote.

## Follow the user's intent

| User intent | Management action |
|---|---|
| “Start this task” | `start`; hand the returned isolated directory to the chosen coding tool |
| “These changes are done” | Confirm external writers have stopped, then `submit` to freeze a delivery |
| “Show the changes and whether they work together” | `review`; present behavior changes, checks, and decisions needed |
| “Try these together before either is accepted” | `review --onto-delivery`; produce a combination preview only |
| “Handle this conflict” | `update`; give the new directory and conflict context to the external AI, then deliver and review the repair |
| “Send this version to GitHub for review” | Read the [GitHub integration](references/github.md); verify authorization, repository scope, and exact versions before publishing a PR or COMMENT |
| “Accept this version” | Establish the exact candidate and destination; local `accept` updates only the isolated state store, not the source project or remote |

If the user is already coding in a tool, hand over the directory returned by the manager; another model invocation is unnecessary. Only when an external CLI must be launched, read the [coding-tool integration](references/coders.md) and use the bundled `coders.py`. The core manager does not write business code; external coding tools perform repairs and tests.

## Keep handoffs trustworthy

- `owner`, `tool`, and `reviewer` are labels. `reviewer` identifies the intended recipient of review material, not proof that the person has reviewed it. Do not invent human approval by entering another name.
- `--handoff` declares that external tools have stopped writing; it does not stop them. Use returned work IDs, attempts, directories, and SHAs exactly as provided. A new attempt preserves the old directory; the old attempt cannot deliver as the new one.
- Run checks against the review's exact candidate SHA before recording `check`. An AI's description or a successful CLI exit cannot replace code and execution evidence.
- `ready` means a candidate is available for review. Local acceptance requires valid human confirmation of that specific review. A new revision, changed baseline, or started repair invalidates old confirmation. Do not ask again when existing authorization still matches.
- A `preview_only` review cannot be accepted. When a pending dependency changes, explicitly select its new version and repeat repair and review. Once the dependency is in team history, follow the local workflow to prepare a new candidate; an old preview never becomes approval.
- Never proactively merge `main`. This package offers no GitHub merge or APPROVE operation. “Send for review” does not mean “accept.” Use current session authorization for remote writes, not permission from a past experiment.
- Preserve failures honestly. When the user chooses another tool, retain the earlier attempt and delivery and record the replacement tool's actual execution. Do not use simulated output to report success.

## Report outcomes to people

Use clear states such as “in progress,” “delivered,” “needs changes,” “ready for review,” and “accepted at the specified destination,” translated into the user's language. Lead with behavior changes and decisions needed, then provide relevant diffs, check evidence, and PR links. Distinguish program facts, AI suggestions, and human decisions.

Read back `status` after an operation. After remote operations, also read back the PR, head/base, and review records. Report PR creation, CI success, AI review, and human approval separately. If a conflict or tool failure stops progress, explain which work is preserved and what input is needed next.

This package is a prototype. The local workflow supports local Git repositories; the GitHub adapter supports only private `newgit-integration-*` test repositories on `github.com`, not arbitrary production repositories. There is no GUI, automatic remote synchronization, or production identity/permission system. Skill files are portable; existing state directories contain absolute paths and worktree associations and must not be bundled or moved with the Skill.
