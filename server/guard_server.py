"""AgentSeed MCP server (hand-written, zero third-party dependencies).

Why hand-written instead of the `mcp` SDK: the SDK API drifts between
releases (e.g. `list_tools`/`call_tool` decorators were removed in newer
versions). A minimal JSON-RPC 2.0 stdio implementation over the standard
library works against Cursor / VS Code / Claude Code / Copilot regardless of
which MCP SDK version the client ships.

Protocol: line-delimited JSON-RPC 2.0 over stdin/stdout (stdio transport).

Tools (10 — the 9 `guard_cli.py` subcommands plus `verify_file` and
`resolve_symbol`):
  - verify_code         -> detect_undefined_symbols
  - resolve_symbol      -> resolve_symbols (write-time existence check)
  - verify_file         -> run_verifier (toolchain adapters + builtin fallback)
  - check_contract      -> check_contract (source vs a written spec)
  - check_imports       -> imported-but-unknown packages (slopsquatting)
  - scan_hallucination  -> scan_hallucination_words
  - check_plugin        -> check_plugin_conformance
  - sandbox_run         -> deterministic command execution (verification channel)
  - schema_validate     -> JSON Schema validation (jsonschema when installed,
                          built-in subset fallback)
  - record_verification -> append one entry to the verification audit log
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import guard_engine as engine  # noqa: E402
from engine.symbols import SUPPORTED_LANGUAGES, canonical_languages  # noqa: E402


VERSION = engine.plugin_version()

# Derived from the language registry so `tools/list` can never advertise a set
# that differs from what verify_code actually dispatches.
CANONICAL_LANGUAGES = canonical_languages()
LANGUAGE_CHOICES = list(SUPPORTED_LANGUAGES)
LANGUAGE_DESCRIPTION = (
    "Source language, one of: " + " | ".join(CANONICAL_LANGUAGES) + " (aliases accepted)."
)

# Protocol versions this server can speak. initialize() echoes the client's
# request when we support it, otherwise falls back to our baseline.
SUPPORTED_PROTOCOL = {"2024-11-05", "2025-03-26", "2025-06-18"}
BASELINE_PROTOCOL = "2024-11-05"

# In-flight cancellable requests (MCP notifications/cancelled support).
_pending_lock = threading.Lock()
_pending: dict = {}  # request id -> {"proc": Popen | None, "cancelled": bool}
_stdout_lock = threading.Lock()

# Loaded once at startup: AGENTSEED_CONFIG env, ${PLUGIN_DATA}/
# agentseed.config.json (Agent Plugins v1.0.0 §9.1), or ./agentseed.config.json.
CONFIG = engine.load_config()
CONFIG_ALLOWLIST = engine.config_str_list(CONFIG, "allowlist")
CONFIG_EXTRA_ALLOWLIST = engine.config_str_list(CONFIG, "extra_allowlist")
CONFIG_SEVERITIES = engine.config_severities(CONFIG)
CONFIG_TIMEOUT = engine.parse_timeout(CONFIG)
CONFIG_EXTRA_TOKENS = engine.config_extra_tokens(CONFIG)
CONFIG_SUPPRESS = engine.config_str_list(CONFIG, "suppress_symbols")
CONFIG_KNOWN_PACKAGES = engine.config_str_list(CONFIG, "known_packages")
CONFIG_SANDBOX_ALLOW = engine.config_str_list(CONFIG, "sandbox_allowed_prefixes")
CONFIG_SANDBOX_ENV = engine.sandbox_env_mode(CONFIG)
CONFIG_PROJECT_INDEX = engine.config_bool(CONFIG, "project_index", True)

for _warn_key in engine.unknown_config_keys(CONFIG):
    print(
        f"[agentseed] WARNING: unknown config key '{_warn_key}' ignored "
        f"(known keys: {sorted(engine.KNOWN_CONFIG_KEYS)})",
        file=sys.stderr,
    )


def _tool(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required,
        },
    }


TOOLS = [
    _tool(
        "verify_code",
        "Static analysis to flag symbols the model may have hallucinated "
        "(called/used but never defined or imported). Covers "
        f"{len(CANONICAL_LANGUAGES)} languages: python via full AST analysis, "
        "typescript/javascript via a lexical pass, and every other registered "
        "language via a config-driven generic lexical engine — the set is "
        "enumerated by the language registry, so a newly registered language "
        "needs no change here. Use before marking a coding task complete. "
        "Returns 'suspects' plus per-symbol 'suspects_detail' line numbers; "
        "names listed in config 'suppress_symbols' are excluded but reported "
        "in 'suppressed'.",
        {
            "source": {"type": "string", "description": "Source code to analyze."},
            "language": {
                "type": "string",
                "description": LANGUAGE_DESCRIPTION,
                "enum": LANGUAGE_CHOICES,
                "default": "python",
            },
        },
        ["source"],
    ),
    _tool(
        "resolve_symbol",
        "Write-time prevention: check whether symbol/package names exist "
        "BEFORE calling them — the complement of verify_code, which judges "
        "code after it is written. A name defined nowhere in the project and "
        "unknown to stdlib/the known-package set is a likely hallucinated "
        "API: resolve it, import it, or drop the call before writing the "
        "code. Returns per-name existence, defining files "
        "('defined_in'), the stdlib/known-package flag, and did-you-mean "
        "suggestions from real project symbols.",
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Symbol or package names to resolve, e.g. "
                "['process_data', 'numpy'].",
            },
            "root": {
                "type": "string",
                "description": "Project root directory (default: inferred from "
                "the server's working directory).",
            },
        },
        ["names"],
    ),
    _tool(
        "verify_file",
        "Verify a file that exists on disk with the best available engine. "
        "engine='auto' (default) runs a project toolchain verifier when "
        "installed — ruff or pyflakes or mypy for Python, tsc for TypeScript, "
        "eslint for JavaScript, go vet for Go, cargo check for Rust, javac "
        "for Java — through the "
        "bounded execution channel (no shell, capped output, timeout, tree "
        "kill), and falls back to the built-in analyzer otherwise; "
        "engine='builtin' forces the built-in analyzer; engine='<name>' "
        "requires that verifier and fails loudly when it is missing. Only "
        "undefined-name diagnostics are reported (the hallucinated-symbol "
        "class); other findings stay the tool's own job. Prefer this over "
        "verify_code for framework code that lexical analysis cannot scope "
        "(React hook destructuring, star imports, cross-file symbols).",
        {
            "path": {"type": "string", "description": "Path to an existing source file."},
            "language": {
                "type": "string",
                "description": "Source language; inferred from the file extension "
                "when omitted.",
            },
            "engine": {
                "type": "string",
                "description": "'auto' (default), 'builtin', or an adapter name "
                "listed by the CLI 'verifiers' subcommand.",
            },
        },
        ["path"],
    ),
    _tool(
        "check_contract",
        "Verify source against a declared contract: 'requires' names must be "
        "defined or imported by the source, 'prohibits' tokens must not "
        "appear. Contract is a JSON string, e.g. "
        '{"requires": ["run"], "prohibits": ["stub"]}. Same language set as '
        "verify_code. Use when a task must satisfy a written spec, not just "
        "avoid undefined symbols.",
        {
            "source": {"type": "string", "description": "Source code to analyze."},
            "contract": {
                "type": "string",
                "description": 'JSON contract: {"requires": [...], "prohibits": [...]}.',
            },
            "language": {
                "type": "string",
                "description": "Source language — same set as verify_code.",
                "enum": LANGUAGE_CHOICES,
                "default": "python",
            },
        },
        ["source", "contract"],
    ),
    _tool(
        "check_imports",
        "Flag top-level imports that are neither Python stdlib nor in the "
        "known-package set (stdlib + common third-party + config "
        "'known_packages') — a possible hallucinated package (slopsquatting, "
        "USENIX Security 2025). With 'manifest' set, scans dependency "
        "MANIFEST text instead of code (requirements/pyproject/package.json; "
        "kind inferred or forced via 'manifest_kind') — the first surface a "
        "hallucinated package touches. Report, not a gate: verify the name "
        "exists in the registry before installing. Code mode is Python only; "
        "other languages return an empty result.",
        {
            "source": {"type": "string", "description": "Source code to analyze."},
            "language": {
                "type": "string",
                "description": "Source language (python supported; others return empty).",
                "default": "python",
            },
            "manifest": {
                "type": "string",
                "description": "Dependency-manifest text to scan instead of code "
                "(requirements.txt / pyproject.toml / package.json content).",
            },
            "manifest_kind": {
                "type": "string",
                "enum": ["requirements", "pyproject", "package.json"],
                "description": "Manifest kind; inferred from content when omitted.",
            },
        },
        ["source"],
    ),
    _tool(
        "scan_hallucination",
        "Scan source for hallucination signals in four groups: stub_code "
        "(stub/mock/fake/placeholder/todo/占位/待实现/...), oversold "
        "(guaranteed/all tests pass/production ready/保证通过/...), fabricated "
        "(simulated/invented/虚构/编造/...), and fabricated_url (placeholder "
        "or reserved-TLD domains like api.yourdomain.com or myapp.test — "
        "phantom squatting; the reserved example.com/net/org/edu set stays "
        "clean). English AND CJK tokens; extend the pool via config "
        "'extra_tokens'. Each hit carries a severity; only error-severity "
        "hits set 'blocking': true. A blocking result means the task is NOT "
        "done — fix the flagged lines or downgrade deliberately via config. "
        "Warning/info hits must be reported but do not block completion.",
        {
            "source": {"type": "string", "description": "Source code to scan."},
            "allowlist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional case-insensitive prefixes to exclude "
                "from matching (e.g. ['Mock(']). Defaults to built-in test-idiom "
                "exclusions; pass [] to disable all exclusions.",
            },
        },
        ["source"],
    ),
    _tool(
        "check_plugin",
        "Validate a plugin directory against Agent Plugins 1.0.0 packaging "
        "(plugin.json / skills / mcp.json). Acts as the spec's missing "
        "official linter.",
        {
            "path": {
                "type": "string",
                "description": "Absolute path to the plugin root directory.",
            },
        },
        ["path"],
    ),
    _tool(
        "sandbox_run",
        "Deterministic execution channel: run a command (no shell) in a "
        "subprocess with a timeout and captured output. Turns 'tests pass' "
        "into an observed fact. Optional behavioral assertions upgrade "
        "'the command ran' to 'it produced the expected result': pass "
        "expected_exit (integer) and/or expect_output (substring of stdout "
        "or stderr) and the result gains an 'expectations' verdict. Use to "
        "verify test suites, type checks, linters, or any claim that "
        "requires running code. "
        "WARNING: this executes real processes on the user's machine — "
        "MUST be gated behind user approval in the client. Commands may be "
        "restricted by config 'sandbox_allowed_prefixes'.",
        {
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command as an argument list, e.g. ['python3', '-m', 'pytest'].",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (1-120, default 30).",
                "default": 30,
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (optional).",
            },
            "expected_exit": {
                "type": "integer",
                "description": "Behavioral assertion: the child's exit code must "
                "equal this; judged in result 'expectations.exit_met'.",
            },
            "expect_output": {
                "type": "string",
                "description": "Behavioral assertion: this substring must appear "
                "in stdout or stderr; judged in result 'expectations.output_met'.",
            },
        },
        ["command"],
    ),
    _tool(
        "schema_validate",
        "Validate structured output (JSON) against a JSON Schema. Uses the "
        "jsonschema library (Draft 2020-12, full keyword coverage) when "
        "installed; otherwise falls back to a built-in subset validator. "
        "Results include which validator ran.",
        {
            "instance": {
                "description": "The value to validate (any JSON value).",
            },
            "schema": {
                "type": "object",
                "description": "The JSON Schema to validate against.",
            },
        },
        ["instance", "schema"],
    ),
    _tool(
        "record_verification",
        "Append one entry to the verification audit log "
        "(verification-log.jsonl under PLUGIN_DATA). The SDD contract "
        "requires a completion report with attached evidence — call this "
        "after verify/scan/sandbox runs to persist what was checked, the "
        "verdict, and a short summary. Pass 'files' (paths verified for the "
        "task) so the gate's coverage stage can name changed-but-unverified "
        "files. Returns the log path and total entries.",
        {
            "task": {
                "type": "string",
                "description": "What was being verified, e.g. 'fix #42 login bug'.",
            },
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "status": {"type": "string", "enum": ["pass", "fail", "skipped"]},
                        "summary": {"type": "string"},
                    },
                    "required": ["tool", "status"],
                },
                "description": "Verification steps performed and their verdicts.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths verified for this task (project-relative preferred); "
                "consumed by the gate's coverage stage.",
            },
            "summary": {"type": "string", "description": "One-line overall conclusion."},
        },
        ["task"],
    ),
]


def _write_response(frame: dict) -> None:
    """Single-writer-guarded stdout frame (safe from worker threads)."""
    with _stdout_lock:
        try:
            sys.stdout.write(json.dumps(frame, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            pass  # client disconnected; nothing to write to


def _execute(name: str, args: dict) -> dict:
    """Run one tool call synchronously; returns the tool's result payload."""
    if name == "verify_code":
        return engine.detect_undefined_symbols(
            args.get("source", ""),
            args.get("language", "python"),
            suppress=CONFIG_SUPPRESS,
        )
    if name == "resolve_symbol":
        root = args.get("root") or engine.find_project_root(os.getcwd()) or os.getcwd()
        return engine.resolve_symbols(
            args.get("names") or [],
            root,
            known_packages=CONFIG_KNOWN_PACKAGES,
        )
    if name == "verify_file":
        return engine.run_verifier(
            args.get("path", ""),
            language=args.get("language") or None,
            engine=args.get("engine") or "auto",
            use_index=CONFIG_PROJECT_INDEX,
        )
    if name == "check_contract":
        return engine.check_contract(
            args.get("source", ""),
            args.get("contract", ""),
            args.get("language", "python"),
        )
    if name == "check_imports":
        if args.get("manifest"):
            return engine.check_manifest(
                args["manifest"],
                kind=args.get("manifest_kind"),
                known_packages=CONFIG_KNOWN_PACKAGES,
            )
        return engine.check_imports(
            args.get("source", ""),
            args.get("language", "python"),
            known_packages=CONFIG_KNOWN_PACKAGES,
        )
    if name == "scan_hallucination":
        # explicit tool arguments win over config-file values
        allowlist = args.get("allowlist")
        if allowlist is None:
            allowlist = engine.merge_allowlist(CONFIG_ALLOWLIST, CONFIG_EXTRA_ALLOWLIST)
        return engine.scan_hallucination_words(
            args.get("source", ""),
            allowlist,
            CONFIG_SEVERITIES,
            extra_tokens=CONFIG_EXTRA_TOKENS,
        )
    if name == "check_plugin":
        return engine.check_plugin_conformance(args.get("path", ""))
    if name == "schema_validate":
        return engine.schema_validate(args.get("instance"), args.get("schema", {}))
    if name == "record_verification":
        return engine.record_verification(
            args.get("task", ""),
            args.get("checks") or [],
            summary=args.get("summary"),
            files=args.get("files"),
        )
    return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}


def _run_call_async(msg_id, name: str, args: dict) -> threading.Thread:
    """Run ANY tools/call request in a daemon thread so a long-running tool
    never blocks the stdio read loop, keeping the session responsive and
    (for sandbox_run) cancellable via notifications/cancelled."""
    entry: dict = {"proc": None, "cancelled": False}
    with _pending_lock:
        _pending[msg_id] = entry

    def finish(payload) -> None:
        with _pending_lock:
            was_cancelled = entry["cancelled"]
            _pending.pop(msg_id, None)
        if was_cancelled:
            return  # cancelled request gets no response (MCP cancellation)
        _write_response({"jsonrpc": "2.0", "id": msg_id, "result": payload})

    def work() -> None:
        try:
            if name == "sandbox_run":
                # register the live process so notifications/cancelled can abort it
                timeout = args.get("timeout")
                result = engine.sandbox_run(
                    args.get("command", []),
                    int(timeout) if timeout is not None else CONFIG_TIMEOUT,
                    args.get("cwd"),
                    allowed_prefixes=CONFIG_SANDBOX_ALLOW,
                    on_proc=lambda proc: entry.__setitem__("proc", proc),
                    env_mode=CONFIG_SANDBOX_ENV,
                    expected_exit=args.get("expected_exit"),
                    expect_output=args.get("expect_output"),
                )
            else:
                result = _execute(name, args)
        except Exception as exc:  # noqa: BLE001 - never kill the session
            finish_error = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
            with _pending_lock:
                was_cancelled = entry["cancelled"]
                _pending.pop(msg_id, None)
            if not was_cancelled:
                _write_response(finish_error)
            return
        finish(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2),
                    }
                ]
            }
        )

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def _handle_cancellation(params: dict) -> None:
    rid = params.get("requestId")
    proc = None
    with _pending_lock:
        entry = _pending.get(rid)
        if entry is not None:
            entry["cancelled"] = True
            proc = entry.get("proc")
    if proc is not None:
        engine.kill_tree(proc)  # unblocks communicate() in the worker thread, tree-wide


def _dispatch(method: str, params: dict) -> dict:
    if method == "tools/list":
        return {"tools": TOOLS}
    return {"isError": True, "content": [{"type": "text", "text": f"Unsupported method: {method}"}]}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _force_utf8_stdio() -> None:
    """Force UTF-8 on stdin/stdout regardless of platform locale.

    On Windows the default text encoding is the ANSI code page (e.g. cp936);
    JSON-RPC traffic is UTF-8, and ``ensure_ascii=False`` responses can raise
    UnicodeEncodeError mid-session. Reconfigure both directions explicitly.
    """
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


# Protocol DoS bound: one JSON-RPC frame may not exceed this many characters
# (~2 MB). Larger lines are rejected unread with a -32600 error (id unknown).
MAX_FRAME_CHARS = 2_000_000


def main() -> None:
    _force_utf8_stdio()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        if len(raw) > MAX_FRAME_CHARS:
            _write_response(
                _error(None, -32600, f"frame too large (> {MAX_FRAME_CHARS} chars); rejected")
            )
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method", "")
        is_notification = "id" not in msg

        try:
            if method == "initialize":
                requested = (msg.get("params") or {}).get("protocolVersion")
                agreed = requested if requested in SUPPORTED_PROTOCOL else BASELINE_PROTOCOL
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": agreed,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "agentseed", "version": VERSION},
                    },
                }
            elif method == "notifications/cancelled":
                _handle_cancellation(msg.get("params") or {})
                continue
            elif method == "ping":
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            elif method.startswith("tools/") and not is_notification:
                params = msg.get("params", {}) or {}
                if method == "tools/call":
                    # every tools/call runs in a worker thread: a long tool
                    # never blocks the read loop; sandbox stays cancellable
                    _run_call_async(
                        msg_id,
                        params.get("name", ""),
                        dict(params.get("arguments", {}) or {}),
                    )
                    continue
                payload = _dispatch(method, params)
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": payload}
            else:
                # JSON-RPC 2.0 §5.1: unknown methods must be reported as the
                # error -32601 (Method not found), not as a result.
                resp = _error(msg_id, -32601, f"Method not found: {method}")
        except Exception as exc:  # noqa: BLE001 - never kill the session
            resp = _error(msg_id, -32603, f"Internal error: {exc}")

        # JSON-RPC 2.0 §4.1 gate: notifications MUST NOT receive a reply,
        # whatever the method (covers ping/initialize sent as notifications).
        if is_notification:
            continue
        _write_response(resp)

    # stdin EOF: a one-shot pipe client (printf ... | guard_server.py) closes
    # stdin immediately after its last request. The workers are daemons, so
    # without this drain the final response is killed mid-flight — a lost
    # tools/call reply looks identical to a server that never ran the tool.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with _pending_lock:
            if not _pending:
                break
        time.sleep(0.05)


if __name__ == "__main__":
    main()
