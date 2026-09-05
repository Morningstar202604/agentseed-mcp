"""AgentSeed deterministic execution channel.

Runs a command (no shell) in a subprocess with timeout and captured output.
Turns "tests pass" into an observed fact.
"""

from __future__ import annotations

from collections import deque
import os
import shutil
import subprocess
import threading


def _decode(raw) -> str:
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else (raw or "")


def _read_bounded(stream, cap: int, sink: list[str]) -> None:
    """Drain a pipe stream into ``sink`` keeping only the last ``cap`` chars.

    Truncation happens WHILE streaming (drop-from-front ring buffer), so a
    child that emits gigabytes of output costs O(cap) memory instead of
    O(output). ``sink`` receives the final tail once EOF is reached.
    """
    chunks: deque[str] = deque()
    size = 0
    while True:
        data = stream.read(65536)
        if not data:
            break
        text = data.decode("utf-8", errors="replace")
        chunks.append(text)
        size += len(text)
        while chunks and size - len(chunks[0]) >= cap:
            size -= len(chunks[0])
            chunks.popleft()
    sink.append("".join(chunks)[-cap:])


def resolve_executable(command_name: str, base_dir: str | None = None) -> str | None:
    """Resolve a command token to the absolute path the OS would execute.

    Path-qualified tokens resolve against ``base_dir`` (the ``cwd`` the
    command will actually run in) so the policy-checked path IS the executed
    path — resolving a relative command against the server's own working
    directory would let a caller-controlled ``cwd`` swap the binary after
    the allowlist check. Bare names (``python``, ``pytest``) go through
    ``PATH`` lookup via ``shutil.which`` — deliberately NOT the raw name:
    on Windows, spawning a relative name lets CreateProcess search the
    process's working directory first, so a malicious ``cwd`` could shadow
    an allowlisted basename with a planted executable. Returns None when a
    bare name cannot be resolved anywhere.
    """
    if not isinstance(command_name, str) or not command_name:
        return None
    has_sep = os.path.sep in command_name or (os.altsep and os.altsep in command_name)
    if not has_sep:
        found = shutil.which(command_name)
        return os.path.abspath(found) if found else None
    if os.path.isabs(command_name):
        return command_name
    if base_dir:
        return os.path.abspath(os.path.join(base_dir, command_name))
    return os.path.abspath(command_name)


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _path_matches(resolved: str, entry: str) -> bool:
    """Directory-prefix match with a mandatory separator boundary."""
    entry_norm = _norm_path(entry)
    return resolved == entry_norm or resolved.startswith(entry_norm + os.sep)


def _name_matches(resolved: str, entry: str) -> bool:
    """Bare-name entry: exact basename equality (with .exe tolerance)."""
    res_base = os.path.basename(resolved)
    entry_base = os.path.basename(os.path.normcase(entry.strip()))
    return res_base == entry_base or res_base == f"{entry_base}.exe"


def _matches_allowlist(resolved: str, prefixes: list[str]) -> bool:
    """Pure check (never executes): basename or bounded path-prefix match."""
    res_norm = _norm_path(resolved)
    for entry in prefixes:
        if not isinstance(entry, str) or not entry.strip():
            continue
        stripped = entry.strip()
        if os.path.sep in stripped or (os.altsep and os.altsep in stripped):
            if _path_matches(res_norm, stripped):
                return True
        elif _name_matches(res_norm, stripped):
            return True
    return False


def _blocked(command_head, prefixes: list[str]) -> dict:
    return {
        "exit_code": -10,
        "stdout": "",
        "stderr": (f"blocked: '{command_head}' is not in sandbox_allowed_prefixes {prefixes}"),
        "timed_out": False,
    }


def kill_tree(proc) -> None:
    """Best-effort process-TREE termination, children included.

    Windows: ``taskkill /F /T`` walks the PID tree. POSIX: the child was
    spawned in its own session (``start_new_session=True``), so SIGKILL on
    the process group reaps the whole tree. Falls back to killing the leader
    alone when either mechanism is unavailable."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception:  # noqa: BLE001 - fall through to leader kill
            pass
    else:
        try:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except Exception:  # noqa: BLE001 - fall through to leader kill
            pass
    try:
        proc.kill()
    except OSError:
        pass


# Environment scrubbing (opt-in via config ``sandbox_env: "scrub"``): drop
# variables whose NAMES look credential-bearing. Best-effort denylist — a
# courtesy leak-reduction measure, NOT a security boundary.
_SECRET_MARKERS = (
    "TOKEN",
    "SECRET",
    "PASSWD",
    "PASSWORD",
    "CREDENTIAL",
    "API_KEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "AUTH",
)


def build_env(env_mode: str | None):
    if env_mode == "scrub":
        return {
            k: v
            for k, v in os.environ.items()
            if not any(marker in k.upper() for marker in _SECRET_MARKERS)
        }
    return None  # inherit


def _run_command(command: list[str], timeout: int, cwd: str | None, on_proc=None, env=None) -> dict:
    """Spawn + wait + capture. Shared by sync and async callers.

    ``on_proc`` (optional callable taking the Popen) lets callers register the
    live process for cancellation. stdin is DEVNULL: sandbox commands never read
    interactive input, and inheriting a piped stdin can deadlock children at
    startup on Windows (observed with MCP stdio servers). POSIX children get
    their own session so ``kill_tree`` can signal the whole group.
    """
    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=(os.name != "nt"),
            close_fds=True,
        )
    except FileNotFoundError as exc:
        return {
            "exit_code": -2,
            "stdout": "",
            "stderr": f"command not found: {exc}",
            "timed_out": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": -9, "stdout": "", "stderr": f"run failed: {exc}", "timed_out": False}
    if callable(on_proc):
        on_proc(proc)
    # Two reader threads keep the response bounded in MEMORY, not just at the
    # end: each pipe is drained incrementally into a tail ring buffer, so a
    # child writing unlimited output cannot balloon the process. Threads (not
    # selectors) because Windows select() does not work on pipes.
    stdout_buf: list[str] = []
    stderr_buf: list[str] = []
    reader_out = threading.Thread(
        target=_read_bounded, args=(proc.stdout, 8000, stdout_buf), daemon=True
    )
    reader_err = threading.Thread(
        target=_read_bounded, args=(proc.stderr, 4000, stderr_buf), daemon=True
    )
    reader_out.start()
    reader_err.start()
    timed_out = False
    try:
        proc.wait(timeout=max(1, min(int(timeout), 120)))
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
    reader_out.join(timeout=5)
    reader_err.join(timeout=5)
    return {
        "exit_code": -1 if timed_out else proc.returncode,
        "stdout": stdout_buf[0] if stdout_buf else "",
        "stderr": stderr_buf[0] if stderr_buf else "",
        "timed_out": timed_out,
    }


def sandbox_run(
    command: list[str],
    timeout: int = 30,
    cwd: str | None = None,
    allowed_prefixes: list[str] | None = None,
    on_proc=None,
    env_mode: str | None = None,
    expected_exit: int | None = None,
    expect_output: str | None = None,
) -> dict:
    """Run a command as a subprocess (no shell) with a timeout.

    Deterministic verification channel: turns "the test passes" into an
    observed fact (exit code + output). No shell means no injection via args;
    output is truncated to a bounded tail WHILE streaming, so even a child
    that floods output cannot blow the server's memory.

    ``allowed_prefixes`` (config: ``sandbox_allowed_prefixes``): when a
    non-empty list, the first argument is resolved to the absolute path the
    OS would actually run (PATH lookup for bare names — never a relative
    spawn, which Windows resolves against the attacker-controllable ``cwd``),
    then checked against the allowlist: entries without a path separator
    match the resolved basename exactly (``python`` also accepts
    ``python.exe``); entries WITH a separator must equal the resolved path or
    be a directory-prefix of it with a separator boundary (so ``C:\\tools\\s``
    cannot match ``C:\\tools\\safe\\x.exe``). Anything unresolved or
    unmatched is refused with exit code -10 WITHOUT running, and matched
    commands execute under their RESOLVED absolute path. None/empty =
    unrestricted (command is passed through verbatim).

    ``env_mode`` (config: ``sandbox_env``): "inherit" (default) passes the
    server environment through; "scrub" drops credential-looking variable
    names before spawn (best-effort denylist, see ``build_env``).

    ``expected_exit`` / ``expect_output`` — optional behavioral assertions
    (executional verification): the run's observed exit code and output are
    judged against them. ``expect_output`` is a substring matched against
    stdout OR stderr. When at least one is given, the result gains an
    ``"expectations"`` verdict dict; without them the result shape is
    unchanged. Assertions never replace the raw observed facts — both stay
    in the result.

    ``on_proc`` (advanced): invoked with the live Popen so async callers can
    register it for cancellation. Timeouts and cancellations kill the whole
    process tree (POSIX process group / Windows taskkill /T), not just the
    direct child.

    Returns:
        {"exit_code": int, "stdout": str, "stderr": str, "timed_out": bool,
         "expectations": {"expected_exit", "exit_met", "expected_output",
                          "output_met", "met"},   # only when asserting
        }
    """
    if not isinstance(command, list) or not command:
        return {
            "exit_code": -3,
            "stdout": "",
            "stderr": "command must be a non-empty list",
            "timed_out": False,
        }
    if allowed_prefixes:
        head = command[0]
        resolved = resolve_executable(head, cwd)
        if resolved is None or not _matches_allowlist(resolved, allowed_prefixes):
            return _blocked(head, list(allowed_prefixes))
        argv = [resolved, *command[1:]]
    else:
        argv = list(command)
    result = _run_command(argv, timeout, cwd, on_proc=on_proc, env=build_env(env_mode))
    if expected_exit is not None or expect_output is not None:
        exit_met = None if expected_exit is None else result["exit_code"] == expected_exit
        output_met = (
            None
            if expect_output is None
            else (expect_output in result["stdout"] or expect_output in result["stderr"])
        )
        result["expectations"] = {
            "expected_exit": expected_exit,
            "exit_met": exit_met,
            "expected_output": expect_output,
            "output_met": output_met,
            "met": all(v for v in (exit_met, output_met) if v is not None),
        }
    return result
