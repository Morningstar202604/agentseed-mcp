"""AgentSeed toolchain verifier adapters.

The built-in analyzers are zero-dependency lexical passes, deliberately
weaker than the real tools a project already uses. An adapter runs the
project's own toolchain (ruff, pyflakes, mypy, tsc, eslint, go vet,
cargo check, javac) through the same bounded execution channel as
``sandbox_run`` — no shell, capped output, tree-kill on timeout — and
normalizes its undefined-name findings into the shape the built-in
analyzer reports (``suspects``).

Policy, stated so nobody has to guess:

- Only the hallucination class is extracted (F821 / TS2304 / "undefined:"
  / E0425 / no-undef). A verifier is not a general linter front-end; the
  tool's other diagnostics stay the tool's own job.
- Adapter binaries are resolved through PATH and executed by absolute path.
  The ``sandbox_allowed_prefixes`` config does NOT gate adapters: invoking
  AgentSeed's CLI/server already implies running the project's declared
  toolchain, and refusing it here would just push users to run the tools
  outside every gate.
- ``engine="auto"`` falls back to the built-in analyzer when no adapter is
  installed or one fails to run; an explicit ``engine=<name>`` fails loudly
  instead of silently degrading.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass

from .index import find_project_root, verify_in_project
from .sandbox import sandbox_run
from .symbols import (
    detect_undefined_symbols,
    language_for_file,
    native_language,
    resolve_language,
)

# Adapters run the project's real toolchain; 60s covers every "check this one
# file" invocation with room to spare (go vet / cargo warm-up included). The
# sandbox's own 120s hard cap still applies.
DEFAULT_TIMEOUT = 60

_TSC_LINE_RE = re.compile(r"^(.+?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.*)$")
_TSC_NAME_RE = re.compile(r"Cannot find name '(\w+)'")
_GOVET_LINE_RE = re.compile(r"^(.+?):(\d+):(?:(\d+):)?\s*(.*)$")
_GOVET_NAME_RE = re.compile(r"undefined:\s*([A-Za-z_]\w*)")
_CARGO_NAME_RE = re.compile(r"cannot find (?:value|function) `(\w+)`")
_ESLINT_NAME_RE = re.compile(r"'([^']+)'\s+is not defined")
# ruff phrases it as: Undefined name `foo` (backticks) — 'foo' in older builds
_RUFF_NAME_RE = re.compile(r"Undefined name [`']([^`']+)[`']")
# mypy: Name "foo" is not defined  [name-defined]  (legacy builds: 'foo')
_MYPY_NAME_RE = re.compile(r"Name [\"']([^\"']+)[\"'] is not defined")
_MYPY_CODE_RE = re.compile(r"\[([\w-]+)\]\s*$")
_MYPY_LINE_RE = re.compile(r"^(.+?):(\d+):\s*error:\s*(.*)$")
# javac: the name lives on the line AFTER "error: cannot find symbol"
_JAVAC_LINE_RE = re.compile(r"^(.+?):(\d+):\s*error:\s*(.*)$")
_JAVAC_SYMBOL_RE = re.compile(r"symbol:\s*(?:variable|method|class)\s+([\w$]+)")


@dataclass(frozen=True)
class VerifierSpec:
    """One toolchain verifier.

    ``args`` is the fixed argument prefix; the target file list is appended
    by the runner — except package-mode tools (cargo), which ignore file
    arguments and operate on the surrounding project directory.
    ``require_module`` gates on an importable Python module instead of a
    PATH binary (the pyflakes adapter runs through the current interpreter).
    """

    name: str
    languages: tuple[str, ...]
    binary: str  # PATH-lookup name; absolute paths are honored as-is
    args: tuple[str, ...]
    parse: str  # output parser id
    codes: tuple[str, ...] = ()  # undefined-name diagnostic codes
    package_mode: bool = False  # run on the project dir, ignore file args
    require_module: str | None = None
    use_stderr: bool = False  # javac reports diagnostics on stderr, not stdout


VERIFIERS: tuple[VerifierSpec, ...] = (
    VerifierSpec(
        name="ruff",
        languages=("python",),
        binary="ruff",
        args=(
            "check",
            "--exit-zero",
            "--select",
            "F821",
            "--no-cache",
            "--output-format",
            "json",
        ),
        parse="ruff-json",
    ),
    VerifierSpec(
        name="pyflakes",
        languages=("python",),
        binary=sys.executable,
        args=("-m", "pyflakes"),
        parse="pyflakes-text",
        require_module="pyflakes",
    ),
    VerifierSpec(
        name="mypy",
        languages=("python",),
        binary="mypy",
        args=("--no-error-summary", "--hide-error-context", "--no-pretty"),
        parse="mypy-text",
        codes=("name-defined",),
    ),
    VerifierSpec(
        name="tsc",
        languages=("typescript",),
        binary="tsc",
        args=("--noEmit", "--pretty", "false"),
        parse="tsc-text",
        codes=("TS2304", "TS2552"),
    ),
    VerifierSpec(
        name="eslint",
        languages=("javascript",),
        binary="eslint",
        args=(
            "--no-eslintrc",
            "--env",
            "es2022,node,browser",
            "--rule",
            '{"no-undef": "error"}',
            "--format",
            "json",
        ),
        parse="eslint-json",
    ),
    VerifierSpec(
        name="govet",
        languages=("go",),
        binary="go",
        args=("vet",),
        parse="govet-text",
    ),
    VerifierSpec(
        name="cargo",
        languages=("rust",),
        binary="cargo",
        args=("check", "--message-format", "json", "--quiet"),
        parse="cargo-json",
        codes=("E0425",),
        package_mode=True,
    ),
    VerifierSpec(
        name="javac",
        languages=("java",),
        binary="javac",
        # -d keeps .class side effects out of the user's tree; javac writes
        # diagnostics to stderr, hence use_stderr
        args=("-d", tempfile.gettempdir()),
        parse="javac-text",
        use_stderr=True,
    ),
)


def _resolve(spec: VerifierSpec) -> str | None:
    """Absolute path of the adapter binary, or None when unavailable."""
    if spec.require_module and importlib.util.find_spec(spec.require_module) is None:
        return None
    if os.path.sep in spec.binary or (os.altsep and os.altsep in spec.binary):
        return spec.binary if os.path.isfile(spec.binary) else None
    found = shutil.which(spec.binary)
    return os.path.abspath(found) if found else None


def _spawn(argv: list[str], timeout: int, cwd: str | None) -> dict:
    # CreateProcess only runs .cmd/.bat shims through the interpreter; npm
    # installs (tsc, eslint) are exactly that on Windows.
    if os.name == "nt" and argv[0].lower().endswith((".cmd", ".bat")):
        argv = ["cmd.exe", "/c", *argv]
    return sandbox_run(argv, timeout, cwd)


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _parse_ruff_json(out: str, codes: tuple[str, ...]) -> list[dict]:
    del codes
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    findings: list[dict] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or item.get("code") != "F821":
            continue
        loc = item.get("location") or {}
        message = item.get("message", "")
        name = _RUFF_NAME_RE.search(message)
        findings.append(
            {
                "file": item.get("filename", ""),
                "line": int(loc.get("row", 0) or 0),
                "name": name.group(1) if name else "",
                "message": message,
                "code": "F821",
                "severity": "error",
            }
        )
    return findings


def _parse_pyflakes_text(out: str, codes: tuple[str, ...]) -> list[dict]:
    del codes
    findings: list[dict] = []
    for line in (out or "").splitlines():
        m = re.match(r"^(.+?):(\d+):(?:(\d+):)?\s*(.*)$", line)
        if not m:
            continue
        message = m.group(4)
        name = re.search(r"undefined name '([^']+)'", message)
        if not name:
            continue
        findings.append(
            {
                "file": m.group(1),
                "line": int(m.group(2)),
                "name": name.group(1),
                "message": message,
                "severity": "error",
            }
        )
    return findings


def _parse_tsc_text(out: str, codes: tuple[str, ...]) -> list[dict]:
    findings: list[dict] = []
    for line in (out or "").splitlines():
        m = _TSC_LINE_RE.match(line.strip())
        if not m or m.group(4) not in codes:
            continue
        name = _TSC_NAME_RE.search(m.group(5))
        findings.append(
            {
                "file": m.group(1),
                "line": int(m.group(2)),
                "name": name.group(1) if name else "",
                "message": m.group(5),
                "code": m.group(4),
                "severity": "error",
            }
        )
    return findings


def _parse_govet_text(out: str, codes: tuple[str, ...]) -> list[dict]:
    del codes
    findings: list[dict] = []
    for line in (out or "").splitlines():
        m = _GOVET_LINE_RE.match(line.strip())
        if not m:
            continue
        name = _GOVET_NAME_RE.search(m.group(4))
        if not name:
            continue
        findings.append(
            {
                "file": m.group(1),
                "line": int(m.group(2)),
                "name": name.group(1),
                "message": m.group(4),
                "severity": "error",
            }
        )
    return findings


def _parse_cargo_json(out: str, codes: tuple[str, ...]) -> list[dict]:
    findings: list[dict] = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("message") or {}
        code = (msg.get("code") or {}).get("code")
        if code not in codes:
            continue
        span = next(
            (s for s in msg.get("spans") or [] if s.get("is_primary")), {}
        )
        name = _CARGO_NAME_RE.search(msg.get("message", ""))
        findings.append(
            {
                "file": span.get("file_name", ""),
                "line": int(span.get("line_start", 0) or 0),
                "name": name.group(1) if name else "",
                "message": msg.get("message", ""),
                "code": code,
                "severity": "error",
            }
        )
    return findings


def _parse_eslint_json(out: str, codes: tuple[str, ...]) -> list[dict]:
    del codes
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    findings: list[dict] = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        for m in entry.get("messages") or []:
            if m.get("ruleId") != "no-undef":
                continue
            name = _ESLINT_NAME_RE.search(m.get("message", ""))
            findings.append(
                {
                    "file": entry.get("filePath", ""),
                    "line": int(m.get("line", 0) or 0),
                    "name": name.group(1) if name else "",
                    "message": m.get("message", ""),
                    "code": "no-undef",
                    "severity": "error",
                }
            )
    return findings


def _parse_mypy_text(out: str, codes: tuple[str, ...]) -> list[dict]:
    findings: list[dict] = []
    for line in (out or "").splitlines():
        m = _MYPY_LINE_RE.match(line.strip())
        if not m:
            continue
        message = m.group(3)
        code_m = _MYPY_CODE_RE.search(message)
        code = code_m.group(1) if code_m else "name-defined"
        if codes and code not in codes:
            continue
        name = _MYPY_NAME_RE.search(message)
        if not name:
            continue
        findings.append(
            {
                "file": m.group(1),
                "line": int(m.group(2)),
                "name": name.group(1),
                "message": message,
                "code": code,
                "severity": "error",
            }
        )
    return findings


def _parse_javac_text(out: str, codes: tuple[str, ...]) -> list[dict]:
    del codes
    findings: list[dict] = []
    lines = (out or "").splitlines()
    for i, line in enumerate(lines):
        m = _JAVAC_LINE_RE.match(line.strip())
        if not m or m.group(3) != "cannot find symbol":
            continue
        name = ""
        if i + 1 < len(lines):
            sm = _JAVAC_SYMBOL_RE.search(lines[i + 1])
            if sm:
                name = sm.group(1)
        findings.append(
            {
                "file": m.group(1),
                "line": int(m.group(2)),
                "name": name,
                "message": m.group(3),
                "severity": "error",
            }
        )
    return findings


_PARSERS = {
    "ruff-json": _parse_ruff_json,
    "pyflakes-text": _parse_pyflakes_text,
    "mypy-text": _parse_mypy_text,
    "tsc-text": _parse_tsc_text,
    "govet-text": _parse_govet_text,
    "cargo-json": _parse_cargo_json,
    "eslint-json": _parse_eslint_json,
    "javac-text": _parse_javac_text,
}

# One diagnostic-shaped line per text parser: what a tool that actually RAN
# looks like even when it found no undefined names of our class.
_DIAG_SHAPE = {
    "pyflakes-text": re.compile(r"^.+?:\d+:"),
    "mypy-text": _MYPY_LINE_RE,
    "tsc-text": _TSC_LINE_RE,
    "govet-text": _GOVET_LINE_RE,
    "javac-text": _JAVAC_LINE_RE,
}


def _has_diagnostic_shape(out: str, parse_id: str) -> bool:
    shape = _DIAG_SHAPE.get(parse_id)
    if shape is None:  # JSON parsers: parseable JSON itself is the shape
        return bool(out.strip())
    return any(shape.match(line.strip()) for line in out.splitlines())


def list_verifiers(language: str | None = None) -> list[dict]:
    """Adapter inventory for humans and `plugin doctor`: name, reach, presence."""
    out: list[dict] = []
    for spec in VERIFIERS:
        if language and language not in spec.languages:
            continue
        out.append(
            {
                "name": spec.name,
                "languages": list(spec.languages),
                "installed": _resolve(spec) is not None,
            }
        )
    return out


def _package_root(path: str) -> str | None:
    """Nearest ancestor directory holding Cargo.toml (cargo is package-mode)."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.isfile(os.path.join(d, "Cargo.toml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _builtin_fallback(full: str, lang: str, note_prefix: str = "", use_index: bool = True) -> dict:
    with open(full, encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    root = find_project_root(full) if use_index else None
    if root is not None:
        result = verify_in_project(source, lang, root)
    else:
        result = detect_undefined_symbols(source, lang)
        result["missing_imports"] = []
    findings = [
        {
            "file": full,
            "line": d.get("line", 0),
            "name": d.get("name"),
            "message": "undefined symbol",
            "severity": "error",
        }
        for d in result.get("suspects_detail", [])
    ]
    if root is not None:
        findings += [
            {
                "file": full,
                "line": d.get("line", 0),
                "name": d.get("name"),
                "message": "defined elsewhere in the project but not imported here",
                "severity": "warning",
            }
            for d in result.get("missing_imports", [])
        ]
    return {
        "ok": True,
        "path": full,
        "language": lang,
        "engine": "builtin",
        "suspects": list(result.get("suspects", [])),
        "missing_imports": list(result.get("missing_imports", [])),
        "findings": findings,
        "note": (
            (note_prefix + " " if note_prefix else "")
            + "No toolchain verifier ran for this language; used the built-in "
            "analyzer. " + result.get("note", "")
        ).strip(),
    }


def _run_spec(spec: VerifierSpec, resolved: str, full: str, lang: str, timeout: int) -> dict:
    cwd = os.path.dirname(full) or None
    if spec.package_mode:
        cwd = _package_root(full) or cwd
        argv = [resolved, *spec.args]
    else:
        argv = [resolved, *spec.args, full]
    proc = _spawn(argv, timeout, cwd)
    if proc["timed_out"]:
        return {
            "ok": False,
            "engine": spec.name,
            "error": f"{spec.name} timed out after {timeout}s",
        }
    if proc["exit_code"] < 0:
        return {
            "ok": False,
            "engine": spec.name,
            "error": proc["stderr"] or f"{spec.name} failed to run (exit {proc['exit_code']})",
        }
    # A tool that exits non-zero with nothing on the diagnostics stream did
    # not report findings — it failed to run (bad flags, bad project).
    # Parsing that as "clean" would be a green light for a scan that never
    # happened.
    out = proc["stderr"] if spec.use_stderr else proc["stdout"]
    other = proc["stdout"] if spec.use_stderr else proc["stderr"]
    if not out.strip() and proc["exit_code"] != 0 and other.strip():
        return {
            "ok": False,
            "engine": spec.name,
            "error": f"{spec.name} produced no parseable output (exit "
            f"{proc['exit_code']}): {other[:200]}",
        }
    findings = _PARSERS[spec.parse](out, spec.codes)
    # Non-zero exit with zero extracted findings: a genuine run that reported
    # only other diagnostic classes (e.g. a syntax error) shows at least one
    # diagnostic-shaped line; a tool that failed to run (bad flags) shows
    # prose instead. Reading prose as "clean" would be a fake green.
    if (
        proc["exit_code"] != 0
        and not findings
        and not _has_diagnostic_shape(out, spec.parse)
    ):
        return {
            "ok": False,
            "engine": spec.name,
            "error": f"{spec.name} produced no parseable output (exit "
            f"{proc['exit_code']}): {out[:200]}",
        }
    suspects = _dedupe([f.get("name") for f in findings if f.get("name")])
    return {
        "ok": True,
        "path": full,
        "language": lang,
        "engine": spec.name,
        "suspects": suspects,
        "findings": findings,
        "note": f"Verified with {spec.name}; only undefined-name diagnostics "
        "are reported here.",
    }


def run_verifier(
    path: str,
    language: str | None = None,
    engine: str = "auto",
    timeout: int = DEFAULT_TIMEOUT,
    use_index: bool = True,
) -> dict:
    """Verify one on-disk file, adapter first, built-in analyzer as fallback.

    ``use_index`` (config ``project_index``) lets the built-in fallback judge
    suspects against a cross-file project symbol index: names defined
    elsewhere in the project are reclassified as missing imports.

    Returns {"ok", "path", "language", "engine", "suspects", "findings",
    "note"} on success, or {"ok": False, "error"} when the request itself is
    invalid (missing file, unknown language, explicit engine not installed).
    """
    if not isinstance(path, str) or not path:
        return {"ok": False, "error": "path must be a non-empty string"}
    full = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(full):
        return {"ok": False, "error": f"not a file: {path}"}
    lang = (language or "").strip().lower() or language_for_file(full) or ""
    if not lang:
        return {
            "ok": False,
            "error": f"cannot infer a language for {path}; pass language=... "
            f"(supported: {', '.join(sorted(_all_verifier_languages()))})",
        }
    if not (native_language(lang) or resolve_language(lang)):
        return {
            "ok": False,
            "error": f"unsupported language '{lang}' — not analyzable by the "
            "built-in engine or any adapter",
        }
    if engine == "builtin":
        return _builtin_fallback(full, lang, use_index=use_index)
    specs = [s for s in VERIFIERS if lang in s.languages]
    if engine != "auto":
        specs = [s for s in specs if s.name == engine]
        if not specs:
            return {
                "ok": False,
                "available": False,
                "error": f"no verifier named '{engine}' for {lang} "
                f"(options: {', '.join(sorted(_langs_to_names().get(lang, []))) or 'none'})",
            }
    failures: list[str] = []
    for spec in specs:
        resolved = _resolve(spec)
        if resolved is None:
            if engine != "auto":
                return {
                    "ok": False,
                    "available": False,
                    "error": f"verifier '{engine}' is not installed",
                }
            continue
        result = _run_spec(spec, resolved, full, lang, timeout)
        if result.get("ok"):
            return result
        if engine != "auto":
            return result  # explicit engine: fail loudly, never degrade silently
        failures.append(f"{spec.name}: {result.get('error', '')}")
    return _builtin_fallback(
        full,
        lang,
        note_prefix=("adapter failures — " + "; ".join(failures) if failures else ""),
        use_index=use_index,
    )


def _all_verifier_languages() -> set[str]:
    out: set[str] = set()
    for spec in VERIFIERS:
        out.update(spec.languages)
    return out


def _langs_to_names() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for spec in VERIFIERS:
        for lang in spec.languages:
            out.setdefault(lang, []).append(spec.name)
    return out
