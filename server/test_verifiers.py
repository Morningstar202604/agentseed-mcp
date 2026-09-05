"""Toolchain verifier adapter tests.

Hermetic by construction: adapters are exercised through stand-in tools
(sys.executable scripts, and a .cmd shim on Windows) so the parser and
runner contract is tested without requiring ruff/tsc/cargo in CI.
"""

import os
import sys
import tempfile
import unittest

from engine import verifiers as V

STANDIN_BODY = (
    "import sys\n"
    "path = sys.argv[1]\n"
    "print(f\"{path}:2:1: undefined name 'magic_unknown'\")\n"
)

BROKEN_BODY = "import sys\nsys.stderr.write('invalid option\\n')\nsys.exit(2)\n"


def _write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class TestRegistryContract(unittest.TestCase):
    def test_every_adapter_targets_a_registered_language(self):
        from engine.symbols import canonical_languages, native_language, resolve_language

        del canonical_languages
        for spec in V.VERIFIERS:
            self.assertTrue(spec.languages, spec.name)
            for lang in spec.languages:
                self.assertTrue(
                    native_language(lang) or resolve_language(lang),
                    f"{spec.name}: unknown language {lang}",
                )

    def test_parser_ids_are_known(self):
        for spec in V.VERIFIERS:
            self.assertIn(spec.parse, V._PARSERS, spec.name)

    def test_list_verifiers_reports_presence(self):
        rows = V.list_verifiers()
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("installed", row)


class TestRunVerifier(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = self._d.name
        self.bad = _write(os.path.join(self.d, "bad.py"), "def f():\n    return magic_unknown()\n")

    def tearDown(self):
        self._d.cleanup()

    def test_missing_file_is_an_error(self):
        res = V.run_verifier(os.path.join(self.d, "nope.py"))
        self.assertFalse(res["ok"])

    def test_unknown_language_is_an_error(self):
        res = V.run_verifier(self.bad, language="klingon")
        self.assertFalse(res["ok"])

    def test_builtin_engine_always_available(self):
        res = V.run_verifier(self.bad, engine="builtin")
        self.assertTrue(res["ok"])
        self.assertEqual(res["engine"], "builtin")
        self.assertIn("magic_unknown", res["suspects"])

    def test_explicit_unknown_engine_fails_loudly(self):
        res = V.run_verifier(self.bad, engine="not-a-tool")
        self.assertFalse(res["ok"])
        self.assertFalse(res.get("available", True))

    def test_standin_adapter_is_parsed(self):
        script = _write(os.path.join(self.d, "standin.py"), STANDIN_BODY)
        spec = V.VerifierSpec(
            name="standin",
            languages=("python",),
            binary=sys.executable,
            args=(script,),
            parse="pyflakes-text",
        )
        original = V.VERIFIERS
        V.VERIFIERS = (spec, *original)
        try:
            res = V.run_verifier(self.bad, engine="standin")
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["suspects"], ["magic_unknown"])
            self.assertEqual(res["findings"][0]["line"], 2)
            # auto prefers the always-installed stand-in over later adapters
            self.assertEqual(V.run_verifier(self.bad, engine="auto")["engine"], "standin")
        finally:
            V.VERIFIERS = original

    def test_auto_falls_back_to_builtin_without_adapters(self):
        original = V.VERIFIERS
        V.VERIFIERS = tuple(s for s in original if s.languages != ("python",))
        try:
            res = V.run_verifier(self.bad, engine="auto")
            self.assertEqual(res["engine"], "builtin")
            self.assertIn("magic_unknown", res["suspects"])
        finally:
            V.VERIFIERS = original

    def test_broken_adapter_output_is_never_read_as_clean(self):
        script = _write(os.path.join(self.d, "brokentool.py"), BROKEN_BODY)
        spec = V.VerifierSpec(
            name="brokentool",
            languages=("python",),
            binary=sys.executable,
            args=(script,),
            parse="pyflakes-text",
        )
        original = V.VERIFIERS
        V.VERIFIERS = (spec,)
        try:
            # explicit: fail loudly, never degrade silently
            res = V.run_verifier(self.bad, engine="brokentool")
            self.assertFalse(res["ok"])
            self.assertIn("no parseable output", res["error"])
            # auto: degrade honestly to the built-in analyzer, failure in note
            res2 = V.run_verifier(self.bad, engine="auto")
            self.assertEqual(res2["engine"], "builtin")
            self.assertIn("brokentool", res2["note"])
            self.assertIn("magic_unknown", res2["suspects"])
        finally:
            V.VERIFIERS = original

    def test_mcp_dispatch_routes_verify_file(self):
        import guard_server

        res = guard_server._execute("verify_file", {"path": self.bad, "engine": "builtin"})
        self.assertIn("magic_unknown", res["suspects"])


@unittest.skipUnless(os.name == "nt", "Windows .cmd shim handling")
class TestWindowsCmdShim(unittest.TestCase):
    def test_cmd_shim_is_wrapped_and_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            tool = _write(
                os.path.join(d, "standin.cmd"),
                "@echo off\n"
                "echo %2:2:1: undefined name 'magic_unknown'\n"
                "exit /b 0\n",
            )
            bad = _write(os.path.join(d, "bad.py"), "def f():\n    return magic_unknown()\n")
            spec = V.VerifierSpec(
                name="cmdtool",
                languages=("python",),
                binary=tool,
                args=(),
                parse="pyflakes-text",
            )
            original = V.VERIFIERS
            V.VERIFIERS = (spec,)
            try:
                res = V.run_verifier(bad, engine="cmdtool")
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["suspects"], ["magic_unknown"])
            finally:
                V.VERIFIERS = original


class TestMypyJavacAdapters(unittest.TestCase):
    """mypy joins the python auto-chain; javac covers java (stderr stream)."""

    def test_mypy_parser_extracts_undefined_names(self):
        out = (
            'x.py:2: error: Name "magic_unknown" is not defined  [name-defined]\n'
            'x.py:3: error: Name "ghost_two" is not defined  [name-defined]\n'
            "x.py:4: error: Incompatible types in assignment  [assignment]\n"
        )
        findings = V._parse_mypy_text(out, ("name-defined",))
        self.assertEqual([f["name"] for f in findings], ["magic_unknown", "ghost_two"])
        self.assertEqual(findings[0]["line"], 2)
        self.assertEqual(findings[0]["code"], "name-defined")

    def test_mypy_parser_legacy_quote_style(self):
        findings = V._parse_mypy_text(
            "x.py:2: error: Name 'ghost' is not defined\n", ("name-defined",)
        )
        self.assertEqual([f["name"] for f in findings], ["ghost"])

    def test_javac_parser_reads_symbol_line(self):
        out = (
            "App.java:5: error: cannot find symbol\n"
            "  symbol:   variable magic_unknown\n"
            "  location: class App\n"
            "App.java:9: error: ';' expected\n"
        )
        findings = V._parse_javac_text(out, ())
        self.assertEqual([f["name"] for f in findings], ["magic_unknown"])
        self.assertEqual(findings[0]["line"], 5)
        self.assertEqual(findings[0]["file"], "App.java")

    def test_javac_runs_from_stderr_stream(self):
        with tempfile.TemporaryDirectory() as d:
            script = _write(
                os.path.join(d, "javastandin.py"),
                "import sys\n"
                "sys.stderr.write('bad.java:5: error: cannot find symbol\\n"
                "  symbol:   variable magic_unknown\\n')\nsys.exit(1)\n",
            )
            bad = _write(
                os.path.join(d, "bad.java"), "class App { void m() { magic_unknown(); } }\n"
            )
            spec = V.VerifierSpec(
                name="javastandin",
                languages=("java",),
                binary=sys.executable,
                args=(script,),
                parse="javac-text",
                use_stderr=True,
            )
            original = V.VERIFIERS
            V.VERIFIERS = (spec,)
            try:
                res = V.run_verifier(bad, engine="javastandin")
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["suspects"], ["magic_unknown"])
            finally:
                V.VERIFIERS = original

    def test_stderr_stream_tool_failure_still_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            script = _write(
                os.path.join(d, "brokenjava.py"),
                "import sys\nsys.stderr.write('javac: invalid flag\\n')\nsys.exit(2)\n",
            )
            bad = _write(os.path.join(d, "bad.java"), "class App {}\n")
            spec = V.VerifierSpec(
                name="brokenjava",
                languages=("java",),
                binary=sys.executable,
                args=(script,),
                parse="javac-text",
                use_stderr=True,
            )
            original = V.VERIFIERS
            V.VERIFIERS = (spec,)
            try:
                # diagnostics stream (stderr) is empty of findings; the failure
                # is on stdout — still "no parseable output", never a fake clean
                res = V.run_verifier(bad, engine="brokenjava")
                self.assertFalse(res["ok"])
                self.assertIn("no parseable output", res["error"])
            finally:
                V.VERIFIERS = original


if __name__ == "__main__":
    unittest.main()
