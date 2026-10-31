"""Run installed coding CLIs in a supplied workspace; preserve native execution evidence."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import os
import signal
import time
import re
import threading


def redactor():
    known = [v for k, v in os.environ.items()
             if re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY)$", k) and len(v) >= 8]

    def clean(value):
        if isinstance(value, dict):
            return {k: "[redacted]" if re.search(r"(?:token|secret|password|api_key|authorization)$", k, re.I)
                    else clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, str):
            return value
        for secret in known:
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"\b(?:sk-ant-[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)",
                       "[redacted]", value)
        return re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9_.~+/=-]+", r"\1[redacted]", value)
    return clean


def review_snapshot(workspace):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
                          capture_output=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=workspace, text=True, capture_output=True, check=True).stdout
    return head, status


def copilot_mcp_names(config_path=None):
    """Read names only so native credentials/configuration never enter evidence."""
    if config_path is None:
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home()))) / ".copilot"
        config_path = root / "mcp-config.json"
    config_path = Path(config_path)
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text())
        servers = config["mcpServers"]
        if not isinstance(servers, dict) or any(
                not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in servers):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Cannot safely enumerate Copilot MCP servers") from None
    return sorted(servers)


def command_for(tool, workspace, output, mode):
    if tool == "codex":
        return ["codex", "exec", "--ephemeral", "--json", "--color", "never",
                "--sandbox", "read-only" if mode == "review" else "workspace-write",
                "--cd", str(workspace), "-"]
    if tool == "copilot":
        # This installed CLI supports prompts on stdin but only plain-text stdout.
        command = ["copilot", "--silent", "--stream", "off", "--no-color",
                   "--log-level", "none", "--disable-builtin-mcps", "--disallow-temp-dir"]
        for name in copilot_mcp_names():
            command.append("--disable-mcp-server=" + name)
        if mode == "review":
            command.extend(["--deny-tool", "write", "shell"])
        else:
            command.extend(["--allow-tool", "write", "shell(python3:*)",
                            "shell(git diff)", "shell(git status)", "shell(git show)",
                            "shell(git rev-parse)"])
        return command
    if tool != "claude":
        raise ValueError("Unknown coding tool")
    file_tools = "Read,Glob,Grep" if mode == "review" else "Read,Write,Edit,Glob,Grep"
    allowed = [file_tools] if mode == "review" else [
        file_tools, "Bash(python3 *)", "Bash(git diff *)", "Bash(git status *)",
        "Bash(git show *)", "Bash(git rev-parse *)"]
    tools = file_tools if mode == "review" else file_tools + ",Bash"
    return ["claude", "-p", "--setting-sources", "user", "--settings", '{"disableAllHooks":true}',
            "--disable-slash-commands", "--no-chrome", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk" if mode == "review" else "acceptEdits",
            "--tools", tools, "--allowedTools", *allowed]


def run(tool, workspace, prompt_file, output, mode="edit", timeout=600):
    workspace, prompt_file, output = [Path(p).resolve() for p in (workspace, prompt_file, output)]
    if not workspace.is_dir() or not prompt_file.is_file():
        raise ValueError("Existing workspace and prompt file are required")
    initial_snapshot = review_snapshot(workspace) if mode == "review" else None
    if initial_snapshot and initial_snapshot[1]:
        raise ValueError("Review requires a clean, fixed checkout")
    clean = redactor()
    output.mkdir(parents=True, exist_ok=False)
    prompt = prompt_file.read_text()
    (output / "prompt.txt").write_text(clean(prompt))
    command = command_for(tool, workspace, output, mode)
    child_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if tool == "copilot":
        child_env.pop("COPILOT_ALLOW_ALL", None)
    manifest = {"tool": tool, "workspace": str(workspace), "mode": mode,
                "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "command": command, "status": "running", "real_cli": True,
                "provider_configuration": "native user settings; no credentials copied"}
    if tool == "copilot":
        manifest.update(output_format="plain_text", session_id=None,
                        success_scope="CLI completion only; requires independent business validation",
                        permissions="tool allowlist and native path checks; not an OS sandbox")
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    started = time.monotonic()
    auth_failed = threading.Event()
    auth_errors = []

    def capture(pipe, destination, inspect=False):
        for line in pipe:
            if tool == "copilot":
                destination.write(clean(line))
                destination.flush()
                if not inspect and re.search(
                        r"No authentication information (?:found|available)|"
                        r"Failed to (?:retrieve|[Gg]et) authentication token|"
                        r"authentication[_ ]failed|"
                        r"\b(?:401|403)\b.*(?:authentication|unauthorized|forbidden)", line, re.I):
                    auth_failed.set()
                continue
            try:
                event = json.loads(line)
                if inspect and event.get("error") == "authentication_failed":
                    auth_errors.append(True)
                    if len(auth_errors) >= 2:
                        auth_failed.set()
                text = json.dumps(clean(event), ensure_ascii=False) + "\n"
            except json.JSONDecodeError:
                text = clean(line)
            destination.write(text)
            destination.flush()
        pipe.close()

    def stop(process):
        if process.poll() is not None:
            return
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    stdout_path = output / ("stdout.txt" if tool == "copilot" else "events.jsonl")
    with stdout_path.open("w") as stdout, (output / "stderr.txt").open("w") as stderr:
        process = subprocess.Popen(command, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True,
                                   env=child_env)
        manifest["pid"] = process.pid
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        readers = [threading.Thread(target=capture, args=(process.stdout, stdout, True)),
                   threading.Thread(target=capture, args=(process.stderr, stderr))]
        for reader in readers:
            reader.start()
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            while process.poll() is None:
                if auth_failed.is_set():
                    manifest["failure_reason"] = "authentication_failed"
                    stop(process)
                    break
                if time.monotonic() - started >= timeout:
                    manifest["timed_out"] = True
                    stop(process)
                    break
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            stop(process)
            raise
        finally:
            for reader in readers:
                reader.join()
    events = []
    for line in ([] if tool == "copilot" else stdout_path.read_text().splitlines()):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if tool == "copilot":
        final_text = stdout_path.read_text().strip()
        (output / "final.txt").write_text(final_text + ("\n" if final_text else ""))
        if auth_failed.is_set():
            manifest["failure_reason"] = "authentication_failed"
        successful = bool(final_text) and not auth_failed.is_set() and not manifest.get("timed_out")
        if not final_text and "failure_reason" not in manifest:
            manifest["failure_reason"] = "missing_response"
    elif tool == "claude":
        result = next((e for e in reversed(events) if e.get("type") == "result"), {})
        (output / "final.txt").write_text(result.get("result", ""))
        successful = result.get("subtype") == "success" and not result.get("is_error", True)
        manifest["session_id"] = result.get("session_id")
        manifest["permission_denials"] = result.get("permission_denials", [])
    else:
        successful = any(e.get("type") == "turn.completed" for e in events)
        successful = successful and not any(e.get("type") == "turn.failed" for e in events)
        manifest["session_id"] = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
        messages = [e["item"].get("text", "") for e in events
                    if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
        (output / "final.txt").write_text(clean(messages[-1] if messages else ""))
    if initial_snapshot is not None:
        manifest["review_workspace_unchanged"] = review_snapshot(workspace) == initial_snapshot
        if not manifest["review_workspace_unchanged"]:
            successful = False
            manifest["failure_reason"] = "review_workspace_changed"
    manifest.update(exit_code=process.returncode, duration_seconds=round(time.monotonic() - started, 2),
                    status="completed" if process.returncode == 0 and successful else "failed",
                    event_count=len(events))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", choices=["codex", "claude", "copilot"], required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["edit", "review"], default="edit")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    result = run(args.tool, args.workspace, args.prompt_file, args.output, args.mode, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
