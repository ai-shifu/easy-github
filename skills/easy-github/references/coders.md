# Handoff to external coding tools

English | [简体中文](zh-CN/coders.md) · [Skill instructions](../SKILL.md)

The Skill manages handoffs. The user's chosen coding tool still writes business code and resolves conflicts. If the user is already working in a coding tool, give it the workspace and task returned by the program directly. **Using the Skill does not require launching another CLI.**

A handoff should include the work intent, permitted change scope, absolute workspace path, base version, work ID, attempt, project validation instructions, and the requirement to stop writing and return control to the management program when finished. A repair task also needs the returned `context_file`. If the tool can only read its assigned directory, embed the necessary context in the prompt instead of expanding its file access.

Tell the coding tool to preserve existing changes made by others and to write code and run checks only in the assigned directory. Leave commits, pushes, PRs, and version management to the management workflow. A tool process exiting does not prove that other editors or background writers have stopped; confirm the handoff before freezing a delivery.

## Optional native CLI runner

If the native CLI is installed and its native login is already configured, the bundled runner can be used:

```bash
python3 "<skill-directory>/scripts/coders.py" --tool codex --workspace "<assigned-workspace>" --prompt-file "<instruction-file>" --output "<new-run-record-directory>" --mode edit --timeout 600
```

`--tool` supports `codex`, `claude`, and `copilot`; `--mode` supports `edit` and `review`. Prompts are passed to the native CLI through stdin. Keep instruction files and run records outside both the business workspace and the Skill installation directory. `--output` must be a new directory; do not overwrite earlier evidence. Existing authorization does not extend to installing another tool or changing its global configuration.

The runner uses the machine's native configuration and authentication. It does not copy credentials into prompts or commits. Retain `manifest.json`, redacted output, `stderr.txt`, and `final.txt`.

Only the current user can access the run-record directory. Redaction covers known environment credentials, common token formats, authentication headers, and sensitive fields or text assignments such as `apiKey` and `x-api-key`. This is best-effort processing and cannot identify every unknown secret format. Keep run records private and inspect their contents before sharing.

| Tool | Native output and completion criteria | Permission boundaries |
|---|---|---|
| Codex | JSON events in `events.jsonl`; recognizes turn completion or failure and records the session ID | `workspace-write` for edit; `read-only` for review |
| Claude Code | JSON events in `events.jsonl`; checks the result's success status | Hooks and additional MCP servers disabled; review limited to Read/Glob/Grep |
| GitHub Copilot CLI | Plain text in `stdout.txt`; records invocation completion only for exit 0, a nonempty response, and no explicit authentication failure | Built-in and configured MCP servers disabled; review disallows shell/write; edit allows writing and an explicit command allowlist |

Copilot does not provide the structured events used here. Its `final.txt` retains the complete native response and tool activity rather than extracting a single conclusion. Claude/Copilot tool allowlists are not operating-system sandboxes. In particular, Python permission in edit mode allows Python code execution; do not claim that arbitrary process or file access is strongly isolated.

CLI versions may change arguments or output formats. If the installed command is incompatible, inspect its native `--help` and retain the failure evidence. Do not infer success from nonexistent events or merely from the presence of an output file. There is no need to force an upgrade of the user's tools for this wrapper.

## Independent review

Obtain the exact candidate to review in a clean, independent Git checkout. Provide explicit base/head versions, the requested scope, and evidence from any known external checks. Then run:

```bash
python3 "<skill-directory>/scripts/coders.py" --tool codex --workspace "<clean-candidate-checkout>" --prompt-file "<review-instruction-file>" --output "<new-review-record-directory>" --mode review --timeout 600
```

The runner requires a clean starting directory and checks whether HEAD or the workspace changed by the end; changes cause failure. Claude/Copilot review does not execute shell commands, so business tests run as a separate step. Reports should distinguish static inspection from tests actually executed by the reviewer. Codex review can execute checks under read-only permissions.

Native CLI completion only proves that the invocation ended. Continue by checking the change scope, actual business behavior, and checks against the fixed candidate before submitting a delivery or recording a review with the management program. AI review comments are not human approval.

## Failures and switching tools

The runner terminates the process group when its timeout is reached. It stops after two consecutive explicit authentication failures for Claude, or after detecting an explicit authentication error for Copilot. Do not clear failure records to retry repeatedly or change global authentication configuration without authorization to conceal the problem.

When the user has authorized a tool change, continue with an available real tool, retain the earlier attempts and failure reasons, and accurately record the replacement tool. The program currently has no command to change an existing work item's tool label. A new work item can clearly identify the replacement tool; if it needs to continue an existing delivery, explicitly provide that content and the current base instead of pretending it migrated automatically. Without confirmation that writing has stopped, do not put a new tool in a directory still being modified by the old one. Do not present a simulation as a real run of another tool.
