"""Trilingual skill parity guard.

The v0.6.0 field pass found two drift classes the other gates cannot see:
the ja skill was missing the whole execution-evidence paragraph, and three
MCP tools (check_contract, check_imports, record_verification) had ZERO
mentions in the skills - so an agent following the skill would never call
them ("you don't say it, it won't do it"). These tests pin parity across
the three languages: same tool surface named, same gate structure, same
new-capability tokens.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "..", "skills", "verify-before-code")

LANG_FILES = ["SKILL.md", "SKILL.zh.md", "SKILL.ja.md"]

# every shipped MCP tool must be instructed in every language's skill
TOOLS = [
    "verify_code", "resolve_symbol", "verify_file", "check_contract",
    "check_imports", "scan_hallucination", "check_plugin", "sandbox_run",
    "schema_validate", "record_verification",
]

# capability tokens the skill must teach, per language, after v0.6.0
CAPABILITY_TOKENS = ["expected_exit", "expect_output", "manifest", "record_verification"]


def _read(name: str) -> str:
    with open(os.path.join(SKILL_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _gates(text: str) -> int:
    return len(re.findall(r"^## .*(?:[Gg]ate|闸门|ゲート)", text, re.M))


class TestTrilingualSkillParity(unittest.TestCase):
    def test_every_tool_is_named_in_every_language(self):
        for lang in LANG_FILES:
            text = _read(lang)
            missing = [t for t in TOOLS if t not in text]
            self.assertEqual(missing, [], f"{lang} does not instruct tools: {missing}")

    def test_gate_structure_count_matches_across_languages(self):
        counts = {lang: _gates(_read(lang)) for lang in LANG_FILES}
        self.assertEqual(len(set(counts.values())), 1, counts)

    def test_capability_tokens_present_in_every_language(self):
        for lang in LANG_FILES:
            text = _read(lang)
            missing = [t for t in CAPABILITY_TOKENS if t not in text]
            self.assertEqual(missing, [], f"{lang} is missing capability tokens: {missing}")

    def test_frontmatter_versions_agree(self):
        versions = set()
        for lang in LANG_FILES:
            m = re.search(r'^\s*version:\s*"([^"]+)"', _read(lang), re.M)
            self.assertIsNotNone(m, f"{lang} frontmatter has no version")
            versions.add(m.group(1))
        self.assertEqual(len(versions), 1, versions)


if __name__ == "__main__":
    unittest.main()
