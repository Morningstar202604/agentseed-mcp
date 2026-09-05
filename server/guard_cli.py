"""AgentSeed CLI — zero-dependency command-line entry point.

Enables CI gating for human PRs as well as agent sessions. One subcommand per
MCP tool:

    python guard_cli.py verify   SOURCE_OR_PATH [--language LANG] [--strict]
    python guard_cli.py contract SOURCE_OR_PATH --contract FILE [--language LANG]
    python guard_cli.py imports  SOURCE_OR_PATH [--known PKG]...
    python guard_cli.py scan     SOURCE_OR_PATH [--strict] [--baseline FILE]
    python guard_cli.py check    [plugin_dir] [--ci]
    python guard_cli.py gate     [--root DIR] [--baseline FILE]
    python guard_cli.py sandbox  -- COMMAND [args...]
    python guard_cli.py record   TASK [--check TOOL=STATUS]... [--note TEXT]

``SOURCE_OR_PATH`` is either inline source text or an existing file path; a
tree is only swept through ``scan --baseline DIR``. A path that does not exist
is a usage error, never silently treated as empty source.

Exit codes: 0 = pass, 1 = findings/errors, 2 = usage error (bad flags, a
directory passed where a file was expected, or a missing path).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

import guard_engine as engine  # noqa: E402
from engine.symbols import SUPPORTED_LANGUAGES, language_for_file, source_extensions  # noqa: E402

# Prose/config formats worth hallucination-scanning. They belong to no language
# in the registry, so they live here; language suffixes do not.
TEXT_EXTENSIONS = (".md", ".json", ".yaml", ".yml", ".toml")

# Derived from the language registry: a language added to the engine becomes
# recognizable here (path-vs-inline heuristic + tree walking) with no edit.
SOURCE_SUFFIXES: tuple[str, ...] = tuple(source_extensions()) + TEXT_EXTENSIONS


def _usage_error(message: str) -> None:
    """Reject the invocation the same way argparse does: stderr + exit 2."""
    print(f"agentseed: {message}", file=sys.stderr)
    raise SystemExit(2)


def _looks_like_path(text: str) -> bool:
    """True when the argument was clearly meant to name a file on disk.

    Inline source is what the CLI also accepts, so the two have to be told
    apart: real code rarely looks like a bare relative path, while a typo'd
    or missing path must never be scanned as if it were source (a guardrail
    that reports ``clean`` for a file that does not exist is worse than one
    that crashes).
    """
    if "\n" in text or "\r" in text:
        return False  # multi-line: inline source
    stripped = text.strip()
    if not stripped:
        return False
    if "/" in text or "\\" in text or os.sep in text:
        return True
    if stripped.startswith((".", "~", "/")):
        return True
    return stripped.lower().endswith(SOURCE_SUFFIXES)


def _read_source(path_or_source: str) -> str:
    if os.path.isdir(path_or_source):
        _usage_error(
            f"'{path_or_source}' is a directory; pass a file path, inline source "
            f"text, or use 'scan <dir> --baseline FILE' to sweep a tree"
        )
    if os.path.isfile(path_or_source):
        with open(path_or_source, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if _looks_like_path(path_or_source):
        _usage_error(
            f"'{path_or_source}' does not exist; pass an existing file path or "
            f"inline source text (a missing path is never scanned as empty source)"
        )
    return path_or_source


def _warn_unknown_config(config: dict) -> None:
    unknown = engine.unknown_config_keys(config)
    for key in unknown:
        print(
            f"[agentseed] WARNING: unknown config key '{key}' ignored "
            f"(known keys: {sorted(engine.KNOWN_CONFIG_KEYS)})",
            file=sys.stderr,
        )


def _config_for_root(root: str | None, explicit: str | None) -> dict:
    """Config discovery that respects the PROJECT being gated, not just the
    process cwd: `agentseed.config.json` at/above the target root wins, then
    the standard search (env / PLUGIN_DATA / cwd). `init` writes the project
    config and gate/verify must actually read it."""
    if explicit:
        return engine.load_config(explicit)
    if root:
        proj_root = engine.find_project_root(root) or (root if os.path.isdir(root) else None)
        if proj_root:
            candidate = os.path.join(proj_root, "agentseed.config.json")
            if os.path.isfile(candidate):
                return engine.load_config(candidate)
    return engine.load_config(None)


def _resolve_language(args: argparse.Namespace) -> str:
    """Explicit ``--language`` wins; otherwise pick the language from the file
    the argument names, falling back to python for inline source text."""
    explicit = getattr(args, "language", None)
    if explicit:
        return explicit
    return language_for_file(args.source) or "python"


def cmd_verify(args: argparse.Namespace) -> int:
    source_path_exists = os.path.isfile(args.source)
    root = (
        engine.find_project_root(args.source)
        if source_path_exists and engine.config_bool(
            _config_for_root(args.source, getattr(args, "config", None)), "project_index", True
        )
        else None
    )
    config = _config_for_root(root, getattr(args, "config", None))
    _warn_unknown_config(config)
    suppress = args.suppress or engine.config_str_list(config, "suppress_symbols")
    language = _resolve_language(args)
    engine_name = getattr(args, "engine", None) or "builtin"
    if engine_name != "builtin" and os.path.isfile(args.source):
        # adapters execute the project's own toolchain on-disk
        result = engine.run_verifier(args.source, language=language, engine=engine_name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok", True):
            return 1
        return 1 if result.get("suspects") else 0
    source = _read_source(args.source)
    # cross-file judgment: a suspect defined elsewhere in the project becomes
    # a missing-import finding (different bug, different fix); `root` is None
    # for inline text, unknown languages, or project_index:false
    if root is not None:
        result = engine.verify_in_project(source, language, root, suppress=suppress)
    else:
        result = engine.detect_undefined_symbols(source, language, suppress=suppress)
    result.setdefault("engine", "builtin")
    if engine_name != "builtin":
        # inline text has no file for an adapter to run against: degrade
        # honestly instead of pretending the toolchain was consulted
        result["note"] = (
            "adapters verify on-disk files; inline source fell back to the "
            "built-in analyzer. " + result.get("note", "")
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("note", "").startswith("Cannot parse"):
        # syntax error is reported, not a finding — unless gating strictly
        return 1 if getattr(args, "strict", False) else 0
    return 1 if (result["suspects"] or result.get("missing_imports")) else 0


def cmd_contract(args: argparse.Namespace) -> int:
    """Contract gate: exit 1 unless every `requires` symbol is defined and
    no `prohibits` token appears."""
    source = _read_source(args.source)
    result = engine.check_contract(source, args.contract, _resolve_language(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["contract_ok"] else 1


def _git_head_text(path: str) -> str | None:
    """Manifest content at git HEAD, or None when not recoverable (not a
    repo / untracked / git missing). Any failure degrades to no baseline —
    the report then flags every unknown, honestly saying so."""
    import subprocess as _sp

    directory = os.path.dirname(os.path.abspath(path)) or "."
    rel = os.path.relpath(os.path.abspath(path), _git_toplevel(directory))
    try:
        proc = _sp.run(
            ["git", "-C", directory, "show", f"HEAD:{rel}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, _sp.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git_toplevel(directory: str) -> str:
    import subprocess as _sp

    try:
        proc = _sp.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, _sp.TimeoutExpired):
        pass
    return directory


def cmd_imports(args: argparse.Namespace) -> int:
    """Slopsquatting gate: exit 1 when a top-level import (or a manifest
    dependency, with --manifest) is neither in the known-package set nor
    resolvable another way (defaults + config known_packages + --known).
    Manifest mode diffs against git HEAD when possible: only NEWLY ADDED
    unknown names are suspicious; pre-existing unknowns are listed apart."""
    config = engine.load_config(getattr(args, "config", None))
    known = args.known or engine.config_str_list(config, "known_packages")
    manifest_path = getattr(args, "manifest", None)
    if manifest_path:
        if not os.path.isfile(manifest_path):
            print(f"error: manifest does not exist: {manifest_path}", file=sys.stderr)
            return 2
        with open(manifest_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        kind = engine.manifest_kind_for_path(manifest_path)
        pre: list[str] | None = None
        head = _git_head_text(manifest_path)
        if head is not None:
            pre = engine.manifest_names(head, kind)
        result = engine.check_manifest(
            text,
            kind=kind,
            known_packages=known,
            preexisting=pre,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["manifest_ok"] else 1
    if not getattr(args, "source", None):
        print("error: provide inline/file source or --manifest", file=sys.stderr)
        return 2
    source = _read_source(args.source)
    result = engine.check_imports(source, known_packages=known)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["imports_ok"] else 1


def _iter_source_files(root: str):
    """Deterministic walk of text sources worth scanning (skips VCS/cache)."""
    skip_dirs = {".git", ".agentseed", "__pycache__", "node_modules", ".github", ".workbuddy"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        for fn in sorted(filenames):
            if fn.lower().endswith(SOURCE_SUFFIXES):
                yield os.path.join(dirpath, fn)


def _fingerprint_counts(source: str, allowlist, severities, extra_tokens) -> dict:
    result = engine.scan_hallucination_words(
        source, allowlist, severities, extra_tokens=extra_tokens
    )
    counts: dict[str, int] = {}
    for h in result["hits"]:
        key = f"{h['group']}|{h['word']}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def cmd_scan_baseline(args: argparse.Namespace) -> int:
    """Baseline mode: fail only on NEW hallucination signals vs a frozen
    fingerprint. Deliberately line-number-free so ordinary edits don't
    churn the baseline; only genuinely new occurrences block."""
    target = os.path.abspath(args.source)
    base_abs = os.path.abspath(args.baseline)
    if os.path.isdir(target):
        files = list(_iter_source_files(target))

        def rel(p: str) -> str:
            return os.path.relpath(p, target).replace(os.sep, "/")
    elif os.path.isfile(target):
        files = [target]

        def rel(p: str) -> str:
            return os.path.basename(p)
    else:
        _usage_error(
            f"'{args.source}' is neither an existing file nor a directory; "
            f"'scan --baseline' sweeps a file or a tree, not inline text"
        )
        return 2

    # never fingerprint the baseline file itself: its own content would
    # re-enter every comparison as "new" signals (self-reference recursion)
    files = [p for p in files if os.path.abspath(p) != base_abs]

    config = _config_for_root(args.source, args.config)
    _warn_unknown_config(config)
    allowlist = (
        []
        if args.strict
        else engine.merge_allowlist(
            args.allowlist or engine.config_str_list(config, "allowlist"),
            engine.config_str_list(config, "extra_allowlist"),
        )
        or engine.DEFAULT_ALLOWLIST
    )
    severities = (
        # registry-driven: every default-warning group blocks under --strict
        {g: "error" for g, s in engine.DEFAULT_SEVERITIES.items() if s == "warning"}
        if (args.strict and not args.stub_ok)
        else engine.config_severities(config)
    )
    extra = engine.config_extra_tokens(config)

    current: dict[str, dict] = {}
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            counts = _fingerprint_counts(fh.read(), allowlist, severities, extra)
        if counts:
            current[rel(path)] = counts

    exists = os.path.isfile(args.baseline)
    if args.update_baseline or not exists:
        payload = {"version": 1, "files": current}
        with open(args.baseline, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        n = sum(sum(c.values()) for c in current.values())
        action = "updated" if exists else "created"
        print(f"baseline {action}: {args.baseline} ({len(current)} files, {n} hits frozen)")
        return 0

    with open(args.baseline, encoding="utf-8") as fh:
        old = json.load(fh).get("files", {})
    grew = []
    for path, counts in sorted(current.items()):
        base = old.get(path, {})
        for key, cnt in counts.items():
            if cnt > base.get(key, 0):
                grew.append((path, key, cnt - base.get(key, 0)))
    if grew:
        print(f"NEW hallucination signals vs baseline ({args.baseline}):")
        for path, key, delta in grew:
            print(f"  +{delta}  {key}  in {path}")
        return 1
    print("baseline check: no NEW hallucination signals")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    if getattr(args, "baseline", None):
        return cmd_scan_baseline(args)
    config = _config_for_root(args.source, args.config)
    _warn_unknown_config(config)
    allowlist = (
        []
        if args.strict
        else engine.merge_allowlist(
            args.allowlist or engine.config_str_list(config, "allowlist"),
            engine.config_str_list(config, "extra_allowlist"),
        )
        or engine.DEFAULT_ALLOWLIST
    )
    severities = (
        # registry-driven: every default-warning group blocks under --strict
        {g: "error" for g, s in engine.DEFAULT_SEVERITIES.items() if s == "warning"}
        if (args.strict and not args.stub_ok)
        else engine.config_severities(config)
    )
    source = _read_source(args.source)
    result = engine.scan_hallucination_words(
        source,
        allowlist,
        severities,
        extra_tokens=engine.config_extra_tokens(config),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["blocking"] else 0


def cmd_check(args: argparse.Namespace) -> int:
    path = os.path.abspath(args.plugin_dir or ".")
    if not os.path.isdir(path):
        print(
            json.dumps(
                {"ok": False, "errors": [f"not a directory: {path}"], "warnings": []},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    result = engine.check_plugin_conformance(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_sandbox(args: argparse.Namespace) -> int:
    config = engine.load_config()
    _warn_unknown_config(config)
    timeout = args.timeout if args.timeout is not None else engine.parse_timeout(config)
    env_mode = getattr(args, "env", None) or engine.sandbox_env_mode(config)
    result = engine.sandbox_run(
        args.command,
        timeout,
        args.cwd,
        allowed_prefixes=engine.config_str_list(config, "sandbox_allowed_prefixes"),
        env_mode=env_mode,
        expected_exit=getattr(args, "expect_exit", None),
        expect_output=getattr(args, "expect_output", None),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("expectations"):
        # with an assertion, the verdict is "matched the expectation", not
        # "exited zero" — the child's real exit code stays in the JSON
        return 0 if result["expectations"]["met"] else 1
    if result["timed_out"]:
        return 1
    if result["exit_code"] < 0:
        return 1  # -2 not found / -9 failed / -10 policy-blocked: never a "pass"
    return result["exit_code"]  # propagate the child's real exit code


def cmd_record(args: argparse.Namespace) -> int:
    checks = []
    for raw in args.check or []:
        tool, _, status = raw.partition("=")
        checks.append({"tool": tool or "manual", "status": status or "pass"})
    result = engine.record_verification(
        args.task,
        checks,
        summary="; ".join(args.note) if args.note else None,
        data_dir=args.data_dir,
        files=args.file or [],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_verifiers(args: argparse.Namespace) -> int:
    """List the toolchain verifier adapters and whether each is installed."""
    print(
        json.dumps(
            {"verifiers": engine.list_verifiers(getattr(args, "language", None))},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_receipt(args: argparse.Namespace) -> int:
    """Build one evidence receipt: checks + file hashes + self digest,
    linked from the JSONL audit log. A completion report cites this."""
    checks = []
    for raw in args.check or []:
        tool, _, status = raw.partition("=")
        checks.append({"tool": tool or "manual", "status": status or "pass"})
    result = engine.build_receipt(
        args.task,
        checks,
        files=args.file,
        summary="; ".join(args.note) if args.note else None,
        data_dir=args.data_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def cmd_plugin_init(args: argparse.Namespace) -> int:
    """Scaffold a minimal conformant plugin, then lint it with the real
    conformance checker — a scaffold that cannot pass its own linter must
    not be left on disk."""
    target = os.path.abspath(args.dir) if args.dir else os.path.join(os.getcwd(), args.name)
    if os.path.exists(target):
        _usage_error(f"refusing to overwrite an existing path: {target}")
    if not _PLUGIN_NAME_OK.match(args.name) or "--" in args.name or ".." in args.name:
        _usage_error(
            f"plugin name {args.name!r} must be lowercase alphanumeric with - and . "
            "only, start and end alphanumeric, no '--' or '..'"
        )
    description = args.description or (
        f"{args.name}: describe in one sentence when a client should load this skill."
    )
    skill_md = (
        f"---\nname: {args.name}\ndescription: >-\n  {description}\n"
        "license: Apache-2.0\n---\n\n"
        f"# {args.name}\n\n"
        "Describe the workflow this skill enforces. Verification tooling is\n"
        "available from the agentseed MCP server (verify_code, verify_file,\n"
        "scan_hallucination, sandbox_run) and the guard_cli equivalents.\n"
    )
    try:
        os.makedirs(os.path.join(target, "skills", args.name))
        with open(os.path.join(target, "plugin.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "$schema": _PLUGIN_SCHEMA,
                    "name": args.name,
                    "version": "0.1.0",
                    "description": description,
                    "license": "Apache-2.0",
                },
                fh,
                indent=2,
            )
            fh.write("\n")
        with open(os.path.join(target, "skills", args.name, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(skill_md)
    except OSError as exc:
        print(f"agentseed: cannot scaffold {target}: {exc}", file=sys.stderr)
        return 1
    result = engine.check_plugin_conformance(target)
    if not result.get("ok"):
        import shutil

        shutil.rmtree(target, ignore_errors=True)
        print(
            json.dumps(
                {"ok": False, "error": "scaffold failed its own linter; tree removed", **result},
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "plugin": target,
                "created": ["plugin.json", f"skills/{args.name}/SKILL.md"],
                "next": [
                    f"agentseed plugin validate {target}",
                    f"agentseed plugin pack {target}",
                ],
            },
            indent=2,
        )
    )
    return 0


# plugin.json §5.5 name shape, checked up front so init fails before creating
# files; '--'/'..' are checked separately (the regex admits single chars only
# at the ends, but not consecutive doubles)
_PLUGIN_NAME_OK = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def cmd_plugin_validate(args: argparse.Namespace) -> int:
    """Conformance check under the toolchain name (`check` stays as-is)."""
    path = os.path.abspath(args.plugin_dir)
    if not os.path.isdir(path):
        print(
            json.dumps(
                {"ok": False, "errors": [f"not a directory: {path}"], "warnings": []},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    result = engine.check_plugin_conformance(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_plugin_pack(args: argparse.Namespace) -> int:
    """Deterministic zip of a plugin root (skip rules shared with the release packer)."""
    result = engine.pack_plugin(args.plugin_dir, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def _mcp_smoke() -> dict:
    """Spawn the real MCP server, initialize, and count tools/list entries."""
    server = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_server.py")
    frames = "\n".join(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                }
            ),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
    )
    try:
        proc = subprocess.run(
            [sys.executable, server],
            input=frames + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics, never a crash
        return {"ok": False, "tools": 0, "error": repr(exc)}
    tools = 0
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        result = msg.get("result")
        if isinstance(result, dict) and "tools" in result:
            tools = len(result["tools"])
    if tools:
        return {"ok": True, "tools": tools, "error": None}
    return {
        "ok": False,
        "tools": 0,
        "error": (proc.stderr.strip()[:200] or "no tools/list response"),
    }


def cmd_plugin_doctor(args: argparse.Namespace) -> int:
    """Environment report: interpreter, optional deps, adapters, config,
    plugin conformance, and a live MCP handshake."""
    import importlib.util
    import platform as _platform

    config = engine.load_config(None)
    report: dict = {
        "agentseed_version": engine.plugin_version(),
        "python": {"version": sys.version.split()[0], "supported": sys.version_info >= (3, 9)},
        "platform": _platform.platform(),
        "optional_dependencies": {
            name: importlib.util.find_spec(name) is not None
            for name in ("jsonschema", "pyflakes", "yaml")
        },
        "toolchain_verifiers": engine.list_verifiers(),
        "config": {"loaded": bool(config), "unknown_keys": engine.unknown_config_keys(config)},
        "mcp_server": _mcp_smoke(),
    }
    root = os.path.abspath(args.plugin_dir or ".")
    if os.path.isfile(os.path.join(root, "plugin.json")):
        report["plugin"] = engine.check_plugin_conformance(root)
    else:
        report["plugin"] = None
    ok = report["python"]["supported"] and (report["plugin"] is None or report["plugin"]["ok"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


_CI_WORKFLOW = """name: AgentSeed gate

on:
  push:
  pull_request:

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          repository: Morningstar202604/AgentSeed
          path: agentseed
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Optional extras (upgrade analyzer engines)
        run: python -m pip install -r agentseed/server/requirements.txt
      - name: Gate
        run: python agentseed/server/guard_cli.py gate --root .
"""


def _write_file_atomic(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _edit_user_config(mutate, config_path: str | None) -> dict:
    """Apply one mutation to the project's agentseed.config.json, atomically.
    A config that exists but cannot be parsed fails loudly — silently
    replacing a broken config with a fresh one would drop every deliberate
    setting the user made."""
    path = os.path.abspath(config_path or os.path.join(os.getcwd(), "agentseed.config.json"))
    data: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"cannot parse {path}: {exc} — fix it by hand"}
        if isinstance(loaded, dict):
            data = loaded
    mutate(data)
    try:
        _write_file_atomic(
            path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    except OSError as exc:
        return {"ok": False, "error": f"cannot write {path}: {exc}"}
    return {"ok": True, "path": path}


def cmd_init(args: argparse.Namespace) -> int:
    """Wire AgentSeed into YOUR project: starter config, CI workflow, first
    gate run (bootstraps the baseline), and the exact snippet to point your
    client at the plugin you cloned."""
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        _usage_error(f"not a directory: {root}")
    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    created: list[str] = []
    skipped: list[str] = []

    cfg_path = os.path.join(root, "agentseed.config.json")
    if os.path.exists(cfg_path) and not args.force:
        skipped.append("agentseed.config.json (exists; --force to overwrite)")
    else:
        _write_file_atomic(
            cfg_path, json.dumps({"project_index": True}, indent=2, sort_keys=True) + "\n"
        )
        created.append("agentseed.config.json")

    workflow_path = os.path.join(root, ".github", "workflows", "agentseed.yml")
    if os.path.exists(workflow_path) and not args.force:
        skipped.append(".github/workflows/agentseed.yml (exists; --force to overwrite)")
    else:
        _write_file_atomic(workflow_path, _CI_WORKFLOW)
        created.append(".github/workflows/agentseed.yml")

    if args.client and args.client != "none":
        hook = os.path.join(plugin_root, "server", "guard_hook.py")
        reg = subprocess.run(
            [sys.executable, hook, "register", "--client", args.client],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if reg.returncode == 0:
            created.append(f"{args.client} hook registered")
        else:
            skipped.append(
                f"{args.client} hook registration failed: "
                + (reg.stderr.strip()[:120] or reg.stdout.strip()[:120])
            )

    gate_ns = argparse.Namespace(
        root=root, baseline=None, no_baseline=False, require_conformance=False, config=None
    )
    gate_rc = cmd_gate(gate_ns)
    gate_note = (
        "first gate run PASS — the baseline is now frozen and enforced"
        if gate_rc == 0
        else "first gate run FAIL — fix the findings or refresh the baseline deliberately (scan --update-baseline)"
    )

    server_py = os.path.join(plugin_root, "server", "guard_server.py")
    print(
        json.dumps(
            {
                "ok": True,
                "project": root,
                "created": created,
                "skipped": skipped,
                "gate": gate_note,
                "wire_your_client": {
                    "mcp_json": {"agentseed": {"command": sys.executable, "args": [server_py]}},
                    "claude_code_cli": f'claude mcp add agentseed -- "{sys.executable}" "{server_py}"',
                    "feedback_loop": "guard_cli suppress NAME (verify stops flagging a project symbol) · guard_cli allow WORD (scan stops flagging a word; merged after the built-in defaults)",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if gate_rc == 0 else 1


def cmd_suppress(args: argparse.Namespace) -> int:
    """One-key noise decay: verify_code stops flagging this project symbol.
    The name is still reported (in 'suppressed'), never silently erased."""

    def mutate(data: dict) -> None:
        names = data.setdefault("suppress_symbols", [])
        if args.name not in names:
            names.append(args.name)

    result = _edit_user_config(mutate, args.config)
    result["effect"] = (
        f"verify_code no longer flags {args.name!r}; it still appears in the "
        "'suppressed' field so the omission stays visible"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_allow(args: argparse.Namespace) -> int:
    """One-key noise decay: scan stops flagging this word. Written to
    extra_allowlist, which merges AFTER the built-in test-idiom defaults —
    allowing one word never drops the defaults."""

    def mutate(data: dict) -> None:
        words = data.setdefault("extra_allowlist", [])
        if args.word not in words:
            words.append(args.word)

    result = _edit_user_config(mutate, args.config)
    result["effect"] = (
        f"scan_hallucination no longer reports {args.word!r} (merged after "
        "the built-in defaults, which stay active)"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_baseline_audit(args: argparse.Namespace) -> int:
    """Report what the frozen scan baseline contains.

    The baseline is the noise-decay mechanism that keeps 'only NEW signals
    fail' livable — and, unreviewed, a permanent hiding place. The audit is
    the review discipline: composition by group, the loudest frozen signals,
    and the prune-and-freeze loop. Report-only: always exits 0.
    """
    path = args.path or "baseline-scan.json"
    payload: dict = {"baseline": os.path.abspath(path)}
    if not os.path.isfile(path):
        payload["ok"] = False
        payload["error"] = (
            f"baseline does not exist: {path} (a gate or 'scan --baseline' run creates it)"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        files = data.get("files") or {}
        if not isinstance(files, dict):
            raise ValueError("files must be an object")
    except (OSError, ValueError) as exc:
        payload["ok"] = False
        payload["error"] = f"cannot read baseline: {exc}"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    totals: dict[str, int] = {}
    for counts in files.values():
        for key, count in (counts or {}).items():
            totals[key] = totals.get(key, 0) + int(count)
    groups: dict[str, int] = {}
    for key, count in totals.items():
        group = key.split("|", 1)[0]
        groups[group] = groups.get(group, 0) + count
    top = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    payload.update(
        {
            "ok": True,
            "schema_version": data.get("version"),
            "files": len(files),
            "hits": sum(totals.values()),
            "distinct_signals": len(totals),
            "groups": dict(sorted(groups.items())),
            "top_frozen_signals": [{"signal": k, "count": v} for k, v in top],
            "advice": (
                "audit is a report: fix what is fixed upstream, allow the "
                "legitimate idioms (guard_cli allow <word>), then freeze the "
                "reduced state with scan --update-baseline. Recreate the audit "
                "after every freeze."
            ),
        }
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    """Composite CI gate — the hard layer behind the soft skill:
    1) plugin conformance (spec linter; skipped on non-plugin roots so the
       gate works on ANY repo — enforce with --require-conformance)
    2) verify_code over every Python file (any suspect or unparseable file fails)
    3) scan with baseline comparison (only NEW signals fail; a first run on a
       repo creates the baseline and passes, enforcement starts on the next)
    4) verification coverage (report only by default; --coverage-strict fails
       when uncommitted changes have no record_verification(files=...) evidence)
    Single exit code: 0 = all gates pass, 1 = any failure."""
    import time

    root = os.path.abspath(args.root)
    started = time.perf_counter()
    summary: dict = {"root": root, "checks": {}}
    failed = False

    # -- 1. conformance ----------------------------------------------------
    if os.path.isfile(os.path.join(root, "plugin.json")):
        conf = engine.check_plugin_conformance(root)
        ok = bool(conf.get("ok"))
        summary["checks"]["conformance"] = {
            "status": "pass" if ok else "fail",
            "errors": conf.get("errors", []),
        }
        failed |= not ok
    elif getattr(args, "require_conformance", False):
        summary["checks"]["conformance"] = {
            "status": "fail",
            "errors": [f"no plugin.json in {root} (--require-conformance)"],
        }
        failed = True
    else:
        summary["checks"]["conformance"] = {
            "status": "skipped",
            "note": f"no plugin.json in {root}: not an Agent Plugins root "
            "(use --require-conformance to enforce)",
        }

    # -- 2. symbols over all Python sources, judged against the project ----
    py_files = [p for p in _iter_source_files(root) if p.endswith(".py")]
    gate_config = _config_for_root(root, args.config)
    use_index = engine.config_bool(gate_config, "project_index", True)
    sym_map = engine.symbol_map(engine.build_index(root)) if use_index else None
    suspects_total: dict[str, list] = {}
    missing_total: dict[str, list] = {}
    unparseable: list[str] = []
    for path in py_files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if sym_map is not None:
            res = engine.verify_in_project(text, "python", root, sym_map=sym_map)
        else:
            res = engine.detect_undefined_symbols(text)
        rel = os.path.relpath(path, root)
        if res.get("note", "").startswith("Cannot parse"):
            unparseable.append(rel)
        if res["suspects"]:
            suspects_total[rel] = res["suspects"]
        if res.get("missing_imports"):
            missing_total[rel] = [m["name"] for m in res["missing_imports"]]
    symbols_ok = not suspects_total and not unparseable and not missing_total
    summary["checks"]["symbols"] = {
        "status": "pass" if symbols_ok else "fail",
        "files_checked": len(py_files),
        "suspects": suspects_total,
        "missing_imports": missing_total,
        "unparseable": unparseable,
    }
    failed |= not symbols_ok

    # -- 3. hallucination scan vs baseline ---------------------------------
    baseline = args.baseline
    if baseline is None and not args.no_baseline:
        # always resolved (not only when the file exists): cmd_scan_baseline
        # creates a missing baseline and passes, so a repo's first gate run
        # bootstraps instead of dead-failing on a file that cannot exist yet
        baseline = os.path.join(root, "baseline-scan.json")
    if args.no_baseline:
        scan_status = "skipped"
    else:
        ns = argparse.Namespace(
            source=root,
            config=args.config,
            strict=False,
            stub_ok=False,
            allowlist=None,
            baseline=baseline,
            update_baseline=False,
        )
        rc = cmd_scan_baseline(ns)
        scan_status = "pass" if rc == 0 else "fail"
        summary["checks"]["scan"] = {"status": scan_status, "baseline": os.path.abspath(baseline)}
        failed |= rc != 0

    # -- 4. verification coverage (report by default, --coverage-strict blocks)
    cov = engine.coverage(root)
    if not cov["computable"]:
        summary["checks"]["coverage"] = {"status": "skipped", "note": cov["note"]}
    elif not cov["changed"]:
        summary["checks"]["coverage"] = {
            "status": "skipped",
            "note": "no uncommitted changes: nothing to cover",
        }
    else:
        strict = getattr(args, "coverage_strict", False)
        unverified = cov["unverified"]
        status = "pass" if not unverified else ("fail" if strict else "report")
        summary["checks"]["coverage"] = {
            "status": status,
            "changed_files": len(cov["changed"]),
            "verified_files": len(cov["verified"]),
            "unverified": unverified,
            "note": cov["note"] if unverified else "",
        }
        failed |= strict and bool(unverified)

    summary["verdict"] = "fail" if failed else "pass"
    summary["elapsed_s"] = round(time.perf_counter() - started, 2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentseed", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify", help="flag possibly-hallucinated symbols")
    p_verify.add_argument("source", help="source code or a file path")
    p_verify.add_argument(
        "--language",
        default=None,
        choices=list(SUPPORTED_LANGUAGES),
        help="default: inferred from the file extension, else python",
    )
    p_verify.add_argument(
        "--strict", action="store_true", help="exit 1 when the source cannot be parsed at all"
    )
    p_verify.add_argument(
        "--suppress",
        action="append",
        metavar="NAME",
        help="symbol name never to flag (repeatable; default: config suppress_symbols)",
    )
    p_verify.add_argument(
        "--engine",
        default=None,
        metavar="ENGINE",
        help="'auto' = best installed toolchain verifier (ruff/pyflakes/tsc/"
        "eslint/go vet/cargo check; falls back to built-in), 'builtin' = the "
        "zero-dependency analyzer (default), or one adapter name (list: "
        "'verifiers'). Adapters need a file path, not inline source.",
    )
    p_verify.add_argument("--config", help="explicit config file path")
    p_verify.set_defaults(func=cmd_verify)

    p_verifiers = sub.add_parser(
        "verifiers", help="list toolchain verifier adapters and install state"
    )
    p_verifiers.add_argument("--language", help="only adapters covering this language")
    p_verifiers.set_defaults(func=cmd_verifiers)

    p_contract = sub.add_parser(
        "contract", help="verify source against a declared contract (requires/prohibits)"
    )
    p_contract.add_argument("source", help="source code or a file path")
    p_contract.add_argument(
        "--contract",
        required=True,
        help='JSON: {"requires": [...], "prohibits": [...]}',
    )
    p_contract.add_argument(
        "--language",
        default=None,
        choices=list(SUPPORTED_LANGUAGES),
        help="default: inferred from the file extension, else python",
    )
    p_contract.set_defaults(func=cmd_contract)

    p_imports = sub.add_parser(
        "imports", help="flag imports not in stdlib / known packages (slopsquatting)"
    )
    p_imports.add_argument(
        "source", nargs="?", default="", help="source code or a file path"
    )
    p_imports.add_argument(
        "--manifest",
        metavar="PATH",
        help="scan a dependency manifest instead (requirements*.txt, "
        "pyproject.toml, package.json; kind inferred from the filename)",
    )
    p_imports.add_argument(
        "--known",
        action="append",
        metavar="PKG",
        help="extra known package (repeatable; default: config known_packages)",
    )
    p_imports.add_argument("--config", help="explicit config file path")
    p_imports.set_defaults(func=cmd_imports)

    p_scan = sub.add_parser("scan", help="scan for hallucination signals")
    p_scan.add_argument("source", help="source text or a file path")
    p_scan.add_argument("--allowlist", action="append", help="exclusion prefix (repeatable)")
    p_scan.add_argument(
        "--strict", action="store_true", help="disable default exclusions; stub hits become errors"
    )
    p_scan.add_argument(
        "--stub-ok", action="store_true", help="with --strict: keep default-warning groups (stub_code, fabricated_url) at warning"
    )
    p_scan.add_argument("--config", help="explicit config file path")
    p_scan.add_argument(
        "--baseline",
        metavar="FILE",
        help="compare against a frozen hit fingerprint; exit 1 "
        "only on NEW signals (source may be a directory)",
    )
    p_scan.add_argument(
        "--update-baseline",
        action="store_true",
        help="(with --baseline) write the current fingerprint and exit 0",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_check = sub.add_parser("check", help="validate a plugin directory")
    p_check.add_argument("plugin_dir", nargs="?", default=".")
    p_check.add_argument(
        "--ci", action="store_true", help="(default in CI use) exit 1 on any conformance error"
    )
    p_check.set_defaults(func=cmd_check)

    p_gate = sub.add_parser("gate", help="composite CI gate: conformance + symbols + baseline scan")
    p_gate.add_argument("--root", default=".", help="plugin/repo root to gate")
    p_gate.add_argument(
        "--baseline", help="scan baseline JSON (default: <root>/baseline-scan.json when present)"
    )
    p_gate.add_argument("--no-baseline", action="store_true", help="skip the scan stage")
    p_gate.add_argument(
        "--coverage-strict",
        action="store_true",
        help="fail when uncommitted changes have no record_verification "
        "evidence (default: report the gap without failing)",
    )
    p_gate.add_argument(
        "--require-conformance",
        action="store_true",
        help="fail when the root has no plugin.json instead of skipping the "
        "conformance stage (for Agent Plugins repos)",
    )
    p_gate.add_argument("--config", help="explicit config file path")
    p_gate.set_defaults(func=cmd_gate)

    p_baseline = sub.add_parser(
        "baseline", help="baseline maintenance (audit: what is frozen, review advice)"
    )
    p_baseline.add_argument("action", choices=["audit"], help="report baseline composition")
    p_baseline.add_argument(
        "path", nargs="?", default=None, help="baseline JSON (default: ./baseline-scan.json)"
    )
    p_baseline.set_defaults(func=cmd_baseline_audit)

    p_sandbox = sub.add_parser("sandbox", help="run a command with timeout + captured output")
    p_sandbox.add_argument(
        "command", nargs="+", help="command to run; use '--' before flags of the child"
    )
    p_sandbox.add_argument("--timeout", type=int, default=None, help="seconds (1-120)")
    p_sandbox.add_argument("--cwd", help="working directory")
    p_sandbox.add_argument(
        "--env",
        choices=engine.SANDBOX_ENV_MODES,
        default=None,
        help="environment policy (default: config sandbox_env / inherit)",
    )
    p_sandbox.add_argument(
        "--expect-exit",
        type=int,
        default=None,
        metavar="N",
        help="behavioral assertion: child exit code must equal N (CLI exits 1 otherwise)",
    )
    p_sandbox.add_argument(
        "--expect-output",
        default=None,
        metavar="STR",
        help="behavioral assertion: STR must appear in stdout or stderr (CLI exits 1 otherwise)",
    )
    p_sandbox.set_defaults(func=cmd_sandbox)

    p_record = sub.add_parser("record", help="append a verification audit entry")
    p_record.add_argument("task", help="what was being verified")
    p_record.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="TOOL=STATUS",
        help="e.g. sandbox_run=pass (repeatable; default pass)",
    )
    p_record.add_argument("--note", action="append", help="free-text note (repeatable)")
    p_record.add_argument(
        "--file",
        action="append",
        metavar="PATH",
        help="file verified for this task (repeatable; feeds the gate's coverage stage)",
    )
    p_record.add_argument("--data-dir", help="override PLUGIN_DATA for the log")
    p_record.set_defaults(func=cmd_record)

    p_receipt = sub.add_parser(
        "receipt",
        help="build an evidence receipt (checks + file SHA256s + self digest)",
    )
    p_receipt.add_argument("task", help="what was verified, e.g. 'fix #42 login bug'")
    p_receipt.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="TOOL=STATUS",
        help="e.g. sandbox_run=pass (repeatable; default pass)",
    )
    p_receipt.add_argument(
        "--file",
        action="append",
        metavar="PATH",
        help="file to hash into the receipt (repeatable; a missing path fails loudly)",
    )
    p_receipt.add_argument("--note", action="append", help="free-text note (repeatable)")
    p_receipt.add_argument("--data-dir", help="override PLUGIN_DATA for the receipt")
    p_receipt.set_defaults(func=cmd_receipt)

    p_plugin = sub.add_parser(
        "plugin", help="Agent Plugins toolchain: init / validate / pack / doctor"
    )
    plugin_sub = p_plugin.add_subparsers(dest="plugin_cmd", required=True)
    p_init = plugin_sub.add_parser("init", help="scaffold a minimal conformant plugin")
    p_init.add_argument("name", help="plugin name (spec §5.5: lowercase, [a-z0-9.-])")
    p_init.add_argument("--dir", help="target directory (default: ./<name>)")
    p_init.add_argument("--description", help="one-sentence plugin description")
    p_init.set_defaults(func=cmd_plugin_init)
    p_pvalidate = plugin_sub.add_parser("validate", help="lint a plugin directory (spec §5/§6/§7)")
    p_pvalidate.add_argument("plugin_dir", nargs="?", default=".")
    p_pvalidate.set_defaults(func=cmd_plugin_validate)
    p_ppack = plugin_sub.add_parser("pack", help="deterministic zip of a plugin root")
    p_ppack.add_argument("plugin_dir", help="Agent Plugins root (must contain plugin.json)")
    p_ppack.add_argument("--out", help="output directory (default: <plugin_dir>/dist)")
    p_ppack.set_defaults(func=cmd_plugin_pack)
    p_doctor = plugin_sub.add_parser(
        "doctor", help="environment report: python, deps, adapters, MCP handshake, conformance"
    )
    p_doctor.add_argument("plugin_dir", nargs="?", default=".", help="optional plugin root to lint")
    p_doctor.set_defaults(func=cmd_plugin_doctor)

    p_init = sub.add_parser(
        "init",
        help="wire AgentSeed into YOUR project: config + CI workflow + first "
        "gate run + the snippet to add the plugin to your client",
    )
    p_init.add_argument("--root", default=".", help="your project directory (default: cwd)")
    p_init.add_argument(
        "--client",
        default="none",
        choices=["none", "claude", "cursor", "opencode"],
        help="also register the enforcement hook for this client",
    )
    p_init.add_argument(
        "--force", action="store_true", help="overwrite an existing config/workflow"
    )
    p_init.set_defaults(func=cmd_init)

    p_suppress = sub.add_parser(
        "suppress",
        help="verify_code stops flagging this symbol (writes agentseed.config.json)",
    )
    p_suppress.add_argument("name", help="symbol name to suppress")
    p_suppress.add_argument("--config", help="explicit config path (default: ./agentseed.config.json)")
    p_suppress.set_defaults(func=cmd_suppress)

    p_allow = sub.add_parser(
        "allow",
        help="scan stops flagging this word (extra_allowlist, merged after the built-in defaults)",
    )
    p_allow.add_argument("word", help="word to stop reporting")
    p_allow.add_argument("--config", help="explicit config path (default: ./agentseed.config.json)")
    p_allow.set_defaults(func=cmd_allow)

    args = parser.parse_args(argv)
    if args.cmd == "sandbox" and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
