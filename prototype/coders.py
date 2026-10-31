"""Run installed coding CLIs in a supplied workspace; preserve native execution evidence."""
import argparse
import codecs
import datetime
import json
from pathlib import Path
import subprocess
import os
import signal
import time
import re
import selectors
import sys


def redactor():
    def sensitive_key(key):
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        return normalized.endswith(("token", "secret", "password", "apikey", "authorization"))

    known = [v for k, v in os.environ.items()
             if sensitive_key(k) and len(v) >= 8]
    assignments = re.compile(
        r'''(?P<quote>["']?)(?P<key>\b[A-Za-z0-9_-]*(?:token|secret|password|api[-_]?key|authorization))'''
        r'''(?P=quote)(?P<sep>\s*[:=]\s*)'''
        r'''(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;]+)''', re.I)

    def clean_assignment(match):
        if not sensitive_key(match["key"]):
            return match[0]
        value_quote = match["value"][0] if match["value"][0] in "\"'" else ""
        return (match["quote"] + match["key"] + match["quote"] + match["sep"]
                + value_quote + "[redacted]" + value_quote)

    def clean(value):
        if isinstance(value, dict):
            return {k: "[redacted]" if sensitive_key(k)
                    else clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, str):
            return value
        for secret in known:
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"\b(?:sk-ant-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)",
                       "[redacted]", value)
        value = re.sub(r"(?i)((?:Bearer|Basic)\s+)[A-Za-z0-9_.~+/=-]+", r"\1[redacted]", value)
        return assignments.sub(clean_assignment, value)
    return clean


def review_snapshot(workspace):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, text=True, encoding="utf-8",
                          capture_output=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=workspace, text=True, encoding="utf-8", capture_output=True, check=True).stdout
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
        config = json.loads(config_path.read_text(encoding="utf-8"))
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
    prompt = prompt_file.read_text(encoding="utf-8")
    command = command_for(tool, workspace, output, mode)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / "prompt.txt").write_text(clean(prompt), encoding="utf-8")
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
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    auth_failed = False
    auth_errors = []

    def capture_line(line, destination, inspect=False):
        nonlocal auth_failed
        if tool == "copilot":
            destination.write(clean(line))
            destination.flush()
            if not inspect and re.search(
                    r"No authentication information (?:found|available)|"
                    r"Failed to (?:retrieve|[Gg]et) authentication token|"
                    r"authentication[_ ]failed|"
                    r"\b(?:401|403)\b.*(?:authentication|unauthorized|forbidden)", line, re.I):
                auth_failed = True
            return
        try:
            event = json.loads(line)
            if inspect and event.get("error") == "authentication_failed":
                auth_errors.append(True)
                if len(auth_errors) >= 2:
                    auth_failed = True
            text = json.dumps(clean(event), ensure_ascii=False) + "\n"
        except json.JSONDecodeError:
            text = clean(line)
        destination.write(text)
        destination.flush()

    stdout_path = output / ("stdout.txt" if tool == "copilot" else "events.jsonl")
    with (stdout_path.open("w", encoding="utf-8") as stdout,
          (output / "stderr.txt").open("w", encoding="utf-8") as stderr,
          selectors.DefaultSelector() as selector):
        process = subprocess.Popen(command, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True,
                                   env=child_env)
        manifest["pid"] = process.pid
        streams = {}
        deadline = started + timeout
        cleanup_started = None
        killed = False

        def signal_group(sig):
            # The process group may still contain children after its leader exits.
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass

        def close_pipe(pipe):
            if pipe.closed:
                return
            try:
                selector.unregister(pipe)
            except KeyError:
                pass
            pipe.close()

        def capture_chunk(pipe, data, final=False):
            stream = streams[pipe]
            stream["pending"] += stream["decoder"].decode(data, final=final)
            while "\n" in stream["pending"]:
                line, stream["pending"] = stream["pending"].split("\n", 1)
                capture_line(line + "\n", stream["destination"], stream["inspect"])
            if final and stream["pending"]:
                capture_line(stream["pending"], stream["destination"], stream["inspect"])
                stream["pending"] = ""

        try:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            pending_input = memoryview(prompt.encode("utf-8"))
            for pipe, destination, inspect in ((process.stdout, stdout, True), (process.stderr, stderr, False)):
                os.set_blocking(pipe.fileno(), False)
                streams[pipe] = {"destination": destination, "inspect": inspect,
                                 "decoder": codecs.getincrementaldecoder("utf-8")("replace"), "pending": ""}
                selector.register(pipe, selectors.EVENT_READ)
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            # Keep the deadline active until both the leader and its output pipes
            # finish. All pipe I/O is nonblocking, including a large input prompt.
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if cleanup_started is None and (auth_failed or now >= deadline):
                    cleanup_started = now
                    if auth_failed:
                        manifest["failure_reason"] = "authentication_failed"
                    else:
                        manifest["timed_out"] = True
                        manifest["failure_reason"] = ("output_drain_timeout" if process.poll() is not None
                                                      else "timeout")
                    signal_group(signal.SIGTERM)
                    close_pipe(process.stdin)
                if cleanup_started is not None and now - cleanup_started >= 0.5 and not killed:
                    signal_group(signal.SIGKILL)
                    killed = True
                if cleanup_started is not None and now - cleanup_started >= 1:
                    # A descendant can escape the group yet retain a pipe. Close
                    # our readers after a bounded drain instead of waiting for EOF.
                    for pipe in list(streams):
                        capture_chunk(pipe, b"", final=True)
                    break
                wake_at = deadline if cleanup_started is None else cleanup_started + (1 if killed else 0.5)
                for key, _ in selector.select(max(0, min(0.1, wake_at - now))):
                    pipe = key.fileobj
                    if pipe is process.stdin:
                        if not pending_input:
                            close_pipe(pipe)
                            continue
                        try:
                            written = os.write(pipe.fileno(), pending_input[:65536])
                            pending_input = pending_input[written:]
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            manifest["failure_reason"] = "prompt_not_delivered"
                            close_pipe(pipe)
                        continue
                    try:
                        data = os.read(pipe.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    capture_chunk(pipe, data, final=not data)
                    if not data:
                        del streams[pipe]
                        close_pipe(pipe)
        except BaseException:
            signal_group(signal.SIGTERM)
            signal_group(signal.SIGKILL)
            raise
        finally:
            if cleanup_started is not None:
                signal_group(signal.SIGKILL)
            for pipe in (process.stdin, process.stdout, process.stderr):
                close_pipe(pipe)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                manifest["failure_reason"] = "process_cleanup_failed"
    events = []
    for line in ([] if tool == "copilot" else stdout_path.read_text(encoding="utf-8").splitlines()):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if tool == "copilot":
        final_text = stdout_path.read_text(encoding="utf-8").strip()
        (output / "final.txt").write_text(final_text + ("\n" if final_text else ""), encoding="utf-8")
        if auth_failed:
            manifest["failure_reason"] = "authentication_failed"
        successful = bool(final_text) and not auth_failed and not manifest.get("timed_out")
        if not final_text and "failure_reason" not in manifest:
            manifest["failure_reason"] = "missing_response"
    elif tool == "claude":
        result = next((e for e in reversed(events) if e.get("type") == "result"), {})
        (output / "final.txt").write_text(result.get("result", ""), encoding="utf-8")
        successful = result.get("subtype") == "success" and not result.get("is_error", True)
        manifest["session_id"] = result.get("session_id")
        manifest["permission_denials"] = result.get("permission_denials", [])
    else:
        successful = any(e.get("type") == "turn.completed" for e in events)
        successful = successful and not any(e.get("type") == "turn.failed" for e in events)
        manifest["session_id"] = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
        messages = [e["item"].get("text", "") for e in events
                    if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
        (output / "final.txt").write_text(clean(messages[-1] if messages else ""), encoding="utf-8")
    if initial_snapshot is not None:
        manifest["review_workspace_unchanged"] = review_snapshot(workspace) == initial_snapshot
        if not manifest["review_workspace_unchanged"]:
            successful = False
            manifest["failure_reason"] = "review_workspace_changed"
    successful = successful and not manifest.get("timed_out") and not manifest.get("failure_reason")
    manifest.update(exit_code=process.returncode, duration_seconds=round(time.monotonic() - started, 2),
                    status="completed" if process.returncode == 0 and successful else "failed",
                    event_count=len(events))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
