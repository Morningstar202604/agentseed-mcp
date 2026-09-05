"""AgentSeed version bumper - one command for the 12-file release bump.

Single source of truth: plugin.json's "version". Everything else echoes it
(package.json, server.json, three READMEs, three DESIGNs, three SKILL
frontmatters). Hand-editing those 12 spots is exactly how "three different
language counts and two different tool counts shipped in the same release"
happened before the doc-sync gate existed.

Usage:
  python scripts/bump.py 0.6.3            # bump every echo site
  python scripts/bump.py 0.6.3 --check    # verify all sites already agree

The CHANGELOG section and the git tag are deliberately NOT touched here:
the changelog describes what shipped (write it by hand), and the tag is
cut by the release chain after merge.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JSON_FILES = ["plugin.json", "package.json", "server.json"]
TEXT_FILES = ["README.md", "README.zh.md", "README.ja.md",
              "DESIGN.md", "DESIGN.zh.md", "DESIGN.ja.md",
              "skills/verify-before-code/SKILL.md",
              "skills/verify-before-code/SKILL.zh.md",
              "skills/verify-before-code/SKILL.ja.md"]


def current_version() -> str:
    with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as fh:
        v = json.load(fh).get("version")
    if not isinstance(v, str) or not re.fullmatch(r"\d+\.\d+\.\d+", v):
        sys.exit(f"plugin.json version {v!r} is not X.Y.Z - fix it by hand")
    return v


def _normalize_json_versions(path: str, target: str, current: str) -> int:
    """Set every X.Y.Z 'version' value in a manifest to target (server.json
    carries both a top-level version and packages[].version)."""
    data = json.load(open(path, encoding="utf-8"))
    changed = 0

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "version" and isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) and v != target:
                    node[k] = target
                    changed += 1
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    if changed or current != target:
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        if data == json.load(open(path, encoding="utf-8")) and current == target and not changed:
            pass
    return changed


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    target = sys.argv[1]
    check = "--check" in sys.argv[2:]
    if not re.fullmatch(r"\d+\.\d+\.\d+", target):
        sys.exit(f"target version {target!r} is not X.Y.Z")
    old = current_version()
    if check:
        drift = []
        for f in JSON_FILES + TEXT_FILES:
            s = open(os.path.join(ROOT, f), encoding="utf-8").read()
            if re.search(r"\d+\.\d+\.\d+", s) and old in s and old != target:
                drift.append(f)
            elif re.search(r'"version":\s*"\d+\.\d+\.\d+"', s) and f in JSON_FILES:
                for m in re.finditer(r'"version":\s*"(\d+\.\d+\.\d+)"', s):
                    if m.group(1) != target:
                        drift.append(f)
        if drift:
            print("drift vs", target, "- stale sites:", ", ".join(sorted(set(drift))))
            return 1
        print("all sites at", target)
        return 0

    changed = []
    for f in JSON_FILES:
        p = os.path.join(ROOT, f)
        n = _normalize_json_versions(p, target, old)
        if n:
            changed.append(f"{f} ({n})")
    for f in TEXT_FILES:
        p = os.path.join(ROOT, f)
        s = open(p, encoding="utf-8").read()
        if old == target:
            break  # nothing to rewrite; the JSON walk already normalized
        n = s.count(old)
        if n:
            open(p, "w", encoding="utf-8", newline="").write(s.replace(old, target))
            changed.append(f"{f} ({n})")
    # normalize any manifest version fields the text pass missed (server.json
    # packages[].version when current == target, etc.)
    for f in JSON_FILES:
        changed_n = _normalize_json_versions(os.path.join(ROOT, f), target, old)
        if changed_n:
            changed.append(f"{f} (+{changed_n})")
    print(f"bumped -> {target}:")
    for c in changed:
        print("  ", c)
    if not changed:
        print("  (all sites already at target)")
    print("next: write the CHANGELOG section, then run "
          "test_docs_sync + test_skill_parity + the full suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
