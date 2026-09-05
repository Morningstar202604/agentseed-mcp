"""AgentSeed verification audit trail (P2-10).

The SDD contract requires a completion report with attached evidence, but
until now nothing persisted verification history. ``record_verification``
appends one JSONL line per call to

    ${PLUGIN_DATA}/verification-log.jsonl   (fallback: ./.agentseed/)

creating a tamper-evident-by-append audit trail agents (or CI) can cite.
Zero dependencies; stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from .version import plugin_version

VALID_STATUSES = {"pass", "fail", "skipped"}


def audit_path(data_dir: str | None = None) -> str:
    base = data_dir or os.environ.get("PLUGIN_DATA") or os.path.join(os.getcwd(), ".agentseed")
    return os.path.join(base, "verification-log.jsonl")


def record_verification(
    task: str,
    checks: list[dict] | None = None,
    summary: str | None = None,
    data_dir: str | None = None,
    files: list[str] | None = None,
) -> dict:
    """Append one verification record; returns {"ok", "path", "entries"}.

    ``files``: paths verified for this task (verbatim, typically relative to
    the project root). The gate's coverage stage reads them back: a changed
    file with no recorded verification is an evidence gap, not a pass.
    """
    if not isinstance(task, str) or not task.strip():
        return {"ok": False, "error": "task must be a non-empty string", "path": "", "entries": 0}
    clean_checks = []
    for c in checks if isinstance(checks, list) else []:
        if not isinstance(c, dict):
            continue
        status = c.get("status")
        if status not in VALID_STATUSES:
            continue
        entry = {"tool": str(c.get("tool", "unknown")), "status": status}
        if isinstance(c.get("summary"), str):
            entry["summary"] = c["summary"]
        clean_checks.append(entry)
    clean_files = []
    for f in files if isinstance(files, list) else []:
        if isinstance(f, str) and f.strip():
            clean_files.append(f.strip())
    path = audit_path(data_dir)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plugin_version": plugin_version(),
        "task": task,
        "checks": clean_checks,
    }
    if isinstance(summary, str) and summary:
        record["summary"] = summary
    if clean_files:
        record["files"] = clean_files
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        return {"ok": False, "error": f"cannot write audit log: {exc}", "path": path, "entries": 0}
    entries = 0
    try:
        with open(path, encoding="utf-8") as fh:
            entries = sum(1 for line in fh if line.strip())
    except OSError:
        pass
    return {"ok": True, "path": path, "entries": entries}


def _norm_repo_path(root: str, path: str) -> str:
    """Normalize a recorded or git-reported path to a comparable form."""
    p = path.strip().strip('"').replace("\\", "/")
    if os.path.isabs(p) or (len(p) > 1 and p[1] == ":"):
        p = os.path.relpath(os.path.abspath(p), root)
    if p.startswith("./"):
        p = p[2:]
    return os.path.normcase(p)


# AgentSeed's own state is never "work": the state directory (verification
# logs, symbol index), the gate-generated scan baseline, and the interpreter's
# bytecode cache must not show up as unverified project changes.
_INTERNAL_STATE_PREFIXES = (".agentseed", "__pycache__")
_INTERNAL_STATE_FILES = {"baseline-scan.json"}


def _is_internal_state(path: str) -> bool:
    norm = path.replace("\\", "/")
    return (
        norm.startswith(_INTERNAL_STATE_PREFIXES) or norm in _INTERNAL_STATE_FILES
    )


def changed_files(root: str) -> list[str] | None:
    """Uncommitted changes (tracked edits + untracked files), git-relative.

    Returns None when root is not a git worktree or git is unavailable —
    coverage degrades to an honest "cannot compute", never to a fake pass.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if "->" in path:  # rename: the destination is the live path
            path = path.split("->", 1)[1]
        path = path.strip().strip('"')
        if path and not _is_internal_state(path):
            out.append(path)
    return out


def verified_files(root: str, data_dir: str | None = None) -> set[str]:
    """Paths recorded via record_verification(files=...) in the project-local
    audit log, normalized for comparison against changed_files()."""
    log = audit_path(data_dir or os.path.join(root, ".agentseed"))
    verified: set[str] = set()
    try:
        with open(log, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                for f in entry.get("files") or []:
                    if isinstance(f, str) and f.strip():
                        verified.add(_norm_repo_path(root, f))
    except OSError:
        pass
    return verified


def coverage(root: str, data_dir: str | None = None) -> dict:
    """Evidence-coverage judgment: changed files vs recorded verifications.

    Closes the self-awareness gap — a receipt freezes what you CLAIM to have
    verified; coverage names what you changed but never verified.
    """
    changed = changed_files(root)
    if changed is None:
        return {
            "root": root,
            "computable": False,
            "changed": [],
            "verified": [],
            "unverified": [],
            "note": "not a git worktree (or git unavailable): change coverage cannot be computed",
        }
    verified = verified_files(root, data_dir)
    changed_norm = [(p, _norm_repo_path(root, p)) for p in changed]
    unverified = [p for p, n in changed_norm if n not in verified]
    verified_changed = [p for p, n in changed_norm if n in verified]
    return {
        "root": root,
        "computable": True,
        "changed": [p for p, _ in changed_norm],
        "verified": verified_changed,
        "unverified": unverified,
        "note": "unverified = changed files with no record_verification(files=...) entry",
    }


def main() -> int:  # pragma: no cover - CLI convenience
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    print(json.dumps(record_verification(args[0]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
