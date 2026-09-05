"""Docs-vs-engine consistency gate.

Everything AgentSeed advertises in prose (how many languages the verifier
covers, how many MCP tools it exposes, which repository is home, which version
is current) is a claim the engine can check. Hand-copied numbers are exactly
where this project drifted before: three different language counts and two
different tool counts shipped in the same release.

These tests make that class of drift a build failure instead of a bug report:
the numbers come from the registry and `tools/list`, and the prose must agree.
"""

from __future__ import annotations

import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

import guard_engine as engine  # noqa: E402
from engine.symbols import canonical_languages  # noqa: E402
from guard_server import TOOLS  # noqa: E402

# Documents that make count/URL/version claims about the shipped plugin.
DOC_FILES = [
    "README.md",
    "README.zh.md",
    "README.ja.md",
    "DESIGN.md",
    "DESIGN.zh.md",
    "DESIGN.ja.md",
]

# The canonical repository: the GitHub home.
REPO_SLUG = "AgentSeed"
# npm package / registry identity (plain `agentseed` is taken by an unrelated publisher).
NPM_SLUG = "agentseed-mcp"
CANONICAL_HOSTS = ("github.com",)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _manifest(name: str) -> dict:
    return json.loads(_read(name))


class TestDocCountsAgreeWithEngine(unittest.TestCase):
    """Any "<N> language(s)" / "<N> 种语言" / "<N> 言語" claim must be the truth."""

    NUMBER_WORDS = r"(\d+|\d+\+)"
    LANG_PATTERNS = [
        re.compile(NUMBER_WORDS + r"\s*(?:languages?|langs?)", re.I),
        re.compile(NUMBER_WORDS + r"\s*(?:种语言|种自然?语言|個の言語|言語)", re.I),
    ]
    TOOL_PATTERNS = [
        re.compile(NUMBER_WORDS + r"\s*MCP\s*(?:tools|工具|ツール)", re.I),
        re.compile(NUMBER_WORDS + r"\s*个\s*MCP\s*工具", re.I),
        re.compile(NUMBER_WORDS + r"\s*(?:tools|工具|ツール)\b", re.I),
        # ja classifiers that slipped past the plain patterns: "8 つの MCP ツール"
        re.compile(NUMBER_WORDS + r"\s*つの\s*MCP\s*ツール", re.I),
        re.compile(NUMBER_WORDS + r"\s*個の\s*MCP\s*ツール", re.I),
    ]
    GROUP_PATTERNS = [
        re.compile(NUMBER_WORDS + r"\s*(?:signal\s*)?groups?", re.I),
        re.compile(NUMBER_WORDS + r"\s*组", re.I),
        re.compile(NUMBER_WORDS + r"\s*グループ", re.I),
    ]

    def setUp(self):
        self.n_languages = len(canonical_languages())
        self.n_tools = len(TOOLS)
        from engine.config import VALID_GROUPS
        self.n_groups = len(VALID_GROUPS)

    def _claims(self, patterns, text, rel):
        out = []
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in patterns:
                for m in pat.finditer(line):
                    out.append((rel, lineno, m.group(1), line.strip()))
        return out

    def test_language_counts_match_registry(self):
        bad = []
        for rel in DOC_FILES:
            for doc_rel, lineno, num, line in self._claims(self.LANG_PATTERNS, _read(rel), rel):
                # "12+" style approximations are the drift we are removing
                if num.rstrip("+") != str(self.n_languages):
                    bad.append(f"{doc_rel}:{lineno}: claims {num!r} languages -> {line[:90]}")
        self.assertEqual(
            bad,
            [],
            f"engine supports {self.n_languages} languages; docs disagree:\n" + "\n".join(bad),
        )

    def test_tool_counts_match_tools_list(self):
        bad = []
        for rel in DOC_FILES:
            for doc_rel, lineno, num, line in self._claims(self.TOOL_PATTERNS, _read(rel), rel):
                text = line.lower()
                # only judge lines that are clearly about AgentSeed's own tool surface
                if not any(k in text for k in ("mcp", "agentseed", "工具", "ツール", "tool")):
                    continue
                if num.rstrip("+") != str(self.n_tools):
                    bad.append(f"{doc_rel}:{lineno}: claims {num!r} tools -> {line[:90]}")
        self.assertEqual(
            bad,
            [],
            f"tools/list exposes {self.n_tools} tools; docs disagree:\n" + "\n".join(bad),
        )

    def test_groups_count_match_engine(self):
        bad = []
        for rel in DOC_FILES:
            for doc_rel, lineno, num, line in self._claims(self.GROUP_PATTERNS, _read(rel), rel):
                text = line.lower()
                if not any(k in text for k in ("mcp", "agentseed", "信号", "シグナル",
                                               "signal", "scan", "工具", "ツール", "group")):
                    continue
                if num.rstrip("+") != str(self.n_groups):
                    bad.append(f"{doc_rel}:{lineno}: claims {num!r} groups -> {line[:90]}")
        self.assertEqual(
            bad,
            [],
            f"engine exposes {self.n_groups} signal groups; docs disagree:\n" + "\n".join(bad),
        )

    def test_verify_code_advertises_the_registry_set(self):
        """The MCP schema must be generated from the same data as the engine."""
        spec = next(t for t in TOOLS if t["name"] == "verify_code")
        langs = spec["inputSchema"]["properties"]["language"]
        self.assertIn("enum", langs, "verify_code.language enum must be registry-derived")
        for canonical in canonical_languages():
            self.assertIn(canonical, langs["enum"], f"{canonical} missing from schema enum")


class TestRepositoryIdentity(unittest.TestCase):
    """One canonical home, everywhere, under the published package name."""

    def _urls(self, text):
        return re.findall(r"(?:git@|https://)([a-z0-9.-]*)/([A-Za-z0-9_.-]+?)(?:\.git)?(?=[\s\"')\],]|$)", text)

    def test_docs_and_manifests_only_reference_known_forges(self):
        offenders = []
        for rel in DOC_FILES + [
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CHANGELOG.md",
            "plugin.json",
            "package.json",
            "server.json",
            "install.sh",
            "install.ps1",
        ]:
            for host, repo in self._urls(_read(rel)):
                if host not in CANONICAL_HOSTS:
                    continue  # shields/badges/registry links live elsewhere
                if repo.rstrip("/") != REPO_SLUG:
                    offenders.append(f"{rel}: {host}/{repo}")
        self.assertEqual(
            offenders,
            [],
            "repository references must all be 'agentseed-mcp' on a known forge:\n"
            + "\n".join(sorted(set(offenders))),
        )

    def test_manifest_homepage_and_repository_agree(self):
        plugin = _manifest("plugin.json")
        pkg = _manifest("package.json")
        server = _manifest("server.json")
        home = f"https://github.com/Morningstar202604/{REPO_SLUG}"
        for label, value in (
            ("plugin.json homepage", plugin.get("homepage")),
            ("plugin.json author.url", (plugin.get("author") or {}).get("url")),
            ("package.json homepage", (pkg.get("homepage") or "").replace("#readme", "")),
            ("package.json repository.url", (pkg.get("repository") or {}).get("url")),
            ("server.json repository.url", (server.get("repository") or {}).get("url")),
        ):
            self.assertTrue(
                str(value).startswith(home), f"{label} = {value!r}, expected the {home} home"
            )

    def test_registry_name_follows_the_canonical_repository(self):
        """Reverse-DNS identity must be derived from where the code actually lives."""
        server = _manifest("server.json")
        self.assertEqual(server.get("name"), f"io.github.morningstar202604/{NPM_SLUG}")
        self.assertEqual(_manifest("package.json").get("mcpName"), server.get("name"))

    def test_server_json_offers_at_least_one_installable_package(self):
        packages = _manifest("server.json").get("packages") or []
        self.assertTrue(packages, "server.json packages[] is empty: the registry entry "
                                  "advertises a server with no installable package")
        for pkg in packages:
            self.assertTrue(pkg.get("name"), "package entry needs a name")
            self.assertTrue(pkg.get("version"), "package entry needs a version")


class TestReferenceLibrary(unittest.TestCase):
    """`references/` on disk is the source of truth; SKILL + README must agree."""

    REF_DIR = os.path.join(ROOT, "skills", "verify-before-code", "references")
    SKILLS = ["skills/verify-before-code/SKILL.md", "skills/verify-before-code/SKILL.zh.md",
              "skills/verify-before-code/SKILL.ja.md"]
    READMES = ["README.md", "README.zh.md", "README.ja.md"]

    def _basenames(self):
        return {f.split(".")[0] for f in os.listdir(self.REF_DIR) if f.endswith(".md")}

    def test_every_skill_lists_every_library(self):
        basenames = self._basenames()
        for rel in self.SKILLS:
            text = _read(rel)
            missing = sorted(b for b in basenames if b not in text)
            self.assertEqual(
                missing, [], f"{rel} does not reference: {missing} (found on disk in references/)"
            )

    def test_every_readme_lists_every_library(self):
        basenames = self._basenames()
        for rel in self.READMES:
            text = _read(rel)
            missing = sorted(b for b in basenames if b not in text)
            self.assertEqual(missing, [], f"{rel} is missing libraries: {missing}")

    def test_referenced_paths_exist(self):
        pattern = re.compile(r"references/([A-Za-z0-9._-]+\.md)")
        broken = []
        for rel in self.SKILLS + self.READMES + DOC_FILES:
            for name in pattern.findall(_read(rel)):
                target = os.path.join(self.REF_DIR, name)
                if not os.path.isfile(target):
                    broken.append(f"{rel} -> references/{name}")
        self.assertEqual(broken, [], "docs point at reference files that do not exist:\n"
                                     + "\n".join(sorted(broken)))


class TestVersionSingleSource(unittest.TestCase):
    """plugin.json is the single source of truth; docs echo it verbatim."""

    def test_version_strings_in_docs_match_the_manifest(self):
        expected = engine.plugin_version()
        bad = []
        for rel in DOC_FILES:
            text = _read(rel)
            for lineno, line in enumerate(text.splitlines(), 1):
                for num in re.findall(r"\b0\.\d+\.\d+\b", line):
                    # changelog-style history lives in CHANGELOG.md only
                    if num != expected:
                        bad.append(f"{rel}:{lineno}: v{num} != v{expected}")
        self.assertEqual(bad, [], "stale version strings in docs:\n" + "\n".join(bad))

    def test_artifact_name_follows_the_package_version(self):
        version = _manifest("package.json")["version"]
        self.assertEqual(_manifest("plugin.json")["version"], version)


if __name__ == "__main__":
    unittest.main()
