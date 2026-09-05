"""AgentSeed project symbol index — cross-file symbol awareness.

Single-file scope analysis is honest but blind to the project: it cannot
tell "this symbol does not exist ANYWHERE" (high-confidence hallucination)
from "defined in another file but not imported here" (a real missing-import
bug with a different fix). The index gives the verifier that judgment.

Design constraints, stated so nobody has to guess:

- Zero dependencies, still lexical. Symbol collection reuses the exact
  per-language collectors behind ``defined_symbols`` — no second parser to
  drift.
- Incremental. Entries are cached per file under ``<root>/.agentseed/`` and
  keyed by content hash; unchanged files are never re-scanned, so a gate on
  a large repo costs seconds, not minutes.
- Differential judgment. A suspect that exists in the index is reclassified
  as a *missing import* (still a real bug, still gate-blocking, but with the
  fix implied: import it — and a did-you-mean list points at the candidates).
  A suspect absent from the index stays a suspect: nothing in the project
  defines it.
- Kill switch. Config ``project_index: false`` turns it off entirely.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import time

from .artifact import SKIP_DIRS
from .symbols import defined_symbols, language_for_file, source_extensions
from .version import plugin_version

INDEX_SCHEMA = "agentseed.index.v1"

# A directory that holds any of these markers is treated as a project root.
PROJECT_MARKERS = (
    ".git",
    "plugin.json",
    "package.json",
    "pyproject.toml",
    "setup.py",
    "go.mod",
    "Cargo.toml",
)

# whole-root walking skips beyond the artifact hygiene set
_INDEX_SKIP_DIRS = {"dist", "node_modules", ".github", ".workbuddy"}


def find_project_root(start: str) -> str | None:
    """Nearest ancestor (or start itself) holding a project marker."""
    d = os.path.abspath(start)
    if os.path.isfile(d):
        d = os.path.dirname(d)
    while True:
        if any(os.path.exists(os.path.join(d, m)) for m in PROJECT_MARKERS):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _iter_source_files(root: str):
    skip = set(SKIP_DIRS) | _INDEX_SKIP_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for fn in sorted(filenames):
            if fn.lower().endswith(source_extensions()):
                yield os.path.join(dirpath, fn)


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def index_path(root: str) -> str:
    return os.path.join(root, ".agentseed", "index.json")


def build_index(root: str) -> dict:
    """Build (or incrementally refresh) the symbol index for a project root.

    Returns the index payload: {"schema", "engine_version", "entries":
    {path: {"hash", "symbols": [...]}}, "stats": {"files", "cached",
    "rescanned", "elapsed_s"}}
    """
    started = time.perf_counter()
    cache_file = index_path(root)
    old_entries: dict = {}
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as fh:
                data = json.load(fh)
            # a cache built by a different engine version may hold judgments
            # from older collection rules — found in the field when the Go
            # masking fix landed: stale v1 caches kept pre-fix symbol lists
            if (
                data.get("schema") == INDEX_SCHEMA
                and data.get("engine_version") == plugin_version()
            ):
                old_entries = data.get("entries", {})
        except (OSError, ValueError):
            old_entries = {}

    entries: dict = {}
    n_files = n_cached = n_rescanned = 0
    for path in _iter_source_files(root):
        n_files += 1
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        try:
            digest = _file_hash(path)
        except OSError:
            continue
        cached = old_entries.get(rel)
        if cached and cached.get("hash") == digest:
            entries[rel] = cached
            n_cached += 1
            continue
        lang = language_for_file(path)
        if not lang:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                symbols = defined_symbols(fh.read(), lang)
        except OSError:
            continue
        entries[rel] = {"hash": digest, "symbols": symbols}
        n_rescanned += 1

    payload = {
        "schema": INDEX_SCHEMA,
        "engine_version": plugin_version(),
        "entries": entries,
        "stats": {
            "files": n_files,
            "cached": n_cached,
            "rescanned": n_rescanned,
            "elapsed_s": round(time.perf_counter() - started, 2),
        },
    }
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        tmp = cache_file + f".tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, cache_file)
    except OSError:
        pass  # a read-only tree still gets in-memory indexing, just no cache
    return payload


def symbol_map(index_payload: dict) -> dict[str, list[str]]:
    """symbol -> sorted file list, derived from the index entries."""
    out: dict[str, list[str]] = {}
    for rel, entry in index_payload.get("entries", {}).items():
        for name in entry.get("symbols", []):
            out.setdefault(name, []).append(rel)
    return {k: sorted(set(v)) for k, v in out.items()}


def load_or_build(root: str) -> dict:
    """build_index, but tolerant: any failure yields an empty index."""
    try:
        return build_index(root)
    except Exception:  # noqa: BLE001 - indexing must never break verification
        return {"schema": INDEX_SCHEMA, "entries": {}, "stats": {"files": 0, "cached": 0, "rescanned": 0, "elapsed_s": 0}}


def suggestions_for(name: str, candidates: set[str], n: int = 3) -> list[str]:
    """Closest real symbols (did-you-mean); empty when nothing is close."""
    if name in candidates:
        return []
    return difflib.get_close_matches(name, candidates, n=n, cutoff=0.6)


def verify_in_project(
    source: str,
    language: str,
    root: str,
    suppress: list[str] | None = None,
    sym_map: dict[str, list[str]] | None = None,
) -> dict:
    """detect_undefined_symbols + project judgment.

    Splits raw suspects into:
      suspects        — not defined anywhere in the project (high-confidence
                        hallucination, carries did-you-mean suggestions)
      missing_imports — defined elsewhere in the project but not imported in
                        this file (a real bug with a different fix)
    ``sym_map`` lets batch callers (gate) build the index once and reuse it.
    """
    from .symbols import detect_undefined_symbols, defined_symbols as _defined

    res = detect_undefined_symbols(source, language, suppress=suppress)
    try:
        local_defined = set(_defined(source, language))
    except Exception:  # noqa: BLE001
        local_defined = set()
    if sym_map is None:
        sym_map = symbol_map(load_or_build(root))
    project_defined = set(sym_map) - local_defined
    candidates = local_defined | set(sym_map)

    detail = res.get("suspects_detail") or []
    if detail:
        missing, nowhere = [], []
        for d in detail:
            entry = dict(d)
            entry["suggestions"] = suggestions_for(d["name"], candidates)
            if d["name"] in project_defined:
                entry["defined_in"] = sym_map.get(d["name"], [])[:5]
                missing.append(entry)
            else:
                nowhere.append(entry)
    else:
        # generic-language passes report names without line detail
        missing, nowhere = [], []
        for name in res.get("suspects", []):
            entry = {"name": name, "suggestions": suggestions_for(name, candidates)}
            if name in project_defined:
                entry["defined_in"] = sym_map.get(name, [])[:5]
                missing.append(entry)
            else:
                nowhere.append(entry)

    res["suspects"] = [e["name"] for e in nowhere]
    res["suspects_detail"] = nowhere
    res["missing_imports"] = missing
    res["note"] = (
        res.get("note", "")
        + f" Project index: {len(sym_map)} project symbols consulted."
    ).strip()
    return res


def index_payload_files(root: str) -> int:
    try:
        with open(index_path(root), encoding="utf-8") as fh:
            return len(json.load(fh).get("entries", {}))
    except (OSError, ValueError):
        return 0


def resolve_symbols(
    names: list[str],
    root: str,
    sym_map: dict[str, list[str]] | None = None,
    known_packages: list[str] | None = None,
) -> dict:
    """Write-time prevention: do these names exist BEFORE the call is written?

    verify_code/verify_file judge code after it is written; this query is the
    complement — ask first, hallucinate never. A name is judged against:
      1. the project symbol index (exists -> which files define it);
      2. Python stdlib + the known-package set (importable without a
         project definition);
      3. nothing else — a name found nowhere is reported as a likely
         hallucinated API, with did-you-mean suggestions from real symbols.
    """
    from .imports import _DEFAULT_COMMON, _pypi_normalize, _stdlib_modules

    clean = []
    seen = set()
    for n in names if isinstance(names, list) else []:
        if isinstance(n, str) and n.strip() and n.strip() not in seen:
            seen.add(n.strip())
            clean.append(n.strip())
    if sym_map is None:
        sym_map = symbol_map(load_or_build(root))
    known = set(sym_map)

    importable = set(_stdlib_modules()) | {_pypi_normalize(p) for p in _DEFAULT_COMMON}
    for pkg in known_packages or []:
        if isinstance(pkg, str) and pkg.strip():
            importable.add(_pypi_normalize(pkg))

    results = []
    for name in clean:
        if name in known:
            results.append(
                {
                    "name": name,
                    "exists": True,
                    "defined_in": sym_map[name][:5],
                    "stdlib_or_known_package": False,
                    "suggestions": [],
                }
            )
            continue
        importable_hit = name in importable or _pypi_normalize(name) in importable
        results.append(
            {
                "name": name,
                "exists": False,
                "defined_in": [],
                "stdlib_or_known_package": importable_hit,
                "suggestions": suggestions_for(name, known),
            }
        )
    return {
        "results": results,
        "all_found": bool(results) and all(r["exists"] or r["stdlib_or_known_package"] for r in results),
        "project_symbols": len(sym_map),
        "note": "Write-time prevention: judged against the project symbol index and "
        "the stdlib/known-package set only. A name found nowhere is a likely "
        "hallucinated API — resolve it, import it, or drop the call before writing "
        "the code. Attribute calls and dependency-internal symbols are not analyzed.",
    }
