"""AgentSeed guard engine unit tests (stdlib unittest, zero deps)."""

import json
import os
import sys
import unittest
from pathlib import Path

import guard_engine as engine  # noqa: E402

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.executable works on every platform; the literal "python3" does not
# exist on many Windows installs (the WindowsApps alias is a Store stub).
PY = sys.executable


class TestUndefinedSymbols(unittest.TestCase):
    def test_catches_hallucinated_call(self):
        r = engine.detect_undefined_symbols("def f():\n    return magic_unknown()\n")
        self.assertIn("magic_unknown", r["suspects"])

    def test_clean_code_passes(self):
        r = engine.detect_undefined_symbols("import math\nprint(math.sqrt(4))\n")
        self.assertEqual(r["suspects"], [])

    def test_syntax_error_reported(self):
        r = engine.detect_undefined_symbols("def f(:\n")
        self.assertEqual(r["suspects"], [])
        self.assertIn("syntax", r["note"])

    def test_ts_catches_hallucinated_call(self):
        src = "import fs from 'fs';\nfunction read(path) { return fs.readFileSync(path); }\nreadFile('../x');\n"
        r = engine.detect_undefined_symbols(src, "typescript")
        self.assertIn("readFile", r["suspects"])

    def test_ts_clean_imports(self):
        src = "import { join } from 'path';\nimport fs from 'fs';\nconsole.log(join('a', 'b'));\nfs.readFileSync('x');\n"
        r = engine.detect_undefined_symbols(src, "typescript")
        self.assertEqual(r["suspects"], [])

    def test_ts_keywords_not_flagged(self):
        src = "function f(x: number) {\n  if (x > 0) return x;\n  return 0;\n}\n"
        r = engine.detect_undefined_symbols(src, "typescript")
        self.assertEqual(r["suspects"], [])

    def test_ts_call_args_are_not_definitions(self):
        # `wrap(helper)` must not define `helper`; `helper()` must be flagged
        src = "helper();\nwrap(helper);\n"
        r = engine.detect_undefined_symbols(src, "typescript")
        self.assertIn("helper", r["suspects"])
        self.assertIn("wrap", r["suspects"])

    def test_ts_multi_declaration_collected(self):
        src = "const a = 1, b = 2;\nconsole.log(a + b);\n"
        r = engine.detect_undefined_symbols(src, "typescript")
        self.assertEqual(r["suspects"], [])

    def test_python_module_dunders_not_flagged(self):
        src = 'if __name__ == "__main__":\n    print(__file__, __doc__)\n'
        r = engine.detect_undefined_symbols(src, "python")
        self.assertEqual(r["suspects"], [])

    def test_python_local_assignment_not_flagged(self):
        src = "def f():\n    total = len([1, 2])\n    return total\n"
        r = engine.detect_undefined_symbols(src, "python")
        self.assertEqual(r["suspects"], [])

    def test_python_for_with_except_targets_not_flagged(self):
        src = (
            "def f(items, path):\n"
            "    out = []\n"
            "    for it in items:\n"
            "        out.append(it)\n"
            "    try:\n"
            "        with open(path) as fh:\n"
            "            out.append(fh.read())\n"
            "    except OSError as exc:\n"
            "        out.append(str(exc))\n"
            "    return out\n"
        )
        r = engine.detect_undefined_symbols(src, "python")
        self.assertEqual(r["suspects"], [])

    def test_python_walrus_and_augassign_not_flagged(self):
        src = "def f(n):\n    count = 0\n    count += n\n    if (big := count * 2) > 10:\n        return big\n    return count\n"
        r = engine.detect_undefined_symbols(src, "python")
        self.assertEqual(r["suspects"], [])

    def test_python_comprehension_and_global_not_flagged(self):
        src = (
            "counter = 0\n"
            "def f(vals):\n"
            "    global counter\n"
            "    counter += 1\n"
            "    return [v * 2 for v in vals]\n"
        )
        r = engine.detect_undefined_symbols(src, "python")
        self.assertEqual(r["suspects"], [])


class TestGenericLanguages(unittest.TestCase):
    """Config-driven generic lexical verify_code for the registered languages."""

    def test_go_catches_hallucinated_call(self):
        src = "package main\n\nfunc main() {\n    ghost()\n}\n"
        r = engine.detect_undefined_symbols(src, "go")
        self.assertIn("ghost", r["suspects"])

    def test_go_clean_defined_and_attribute_calls(self):
        src = (
            "package main\n"
            'import "fmt"\n'
            "func helper(x int) int { return x * 2 }\n"
            "func main() {\n"
            "    fmt.Println(helper(21))\n"
            "}\n"
        )
        r = engine.detect_undefined_symbols(src, "golang")
        self.assertEqual(r["suspects"], [])

    def test_go_short_declaration_not_flagged(self):
        src = "func main() {\n    total := 0\n    total += 1\n}\n"
        r = engine.detect_undefined_symbols(src, "go")
        self.assertEqual(r["suspects"], [])

    def test_rust_catches_hallucinated_call(self):
        src = "fn main() {\n    ghost();\n}\n"
        r = engine.detect_undefined_symbols(src, "rust")
        self.assertIn("ghost", r["suspects"])

    def test_rust_clean_module_with_path_calls(self):
        src = (
            "use std::io;\n"
            "fn helper(x: i32) -> i32 { x + 1 }\n"
            "fn main() {\n"
            "    let y = helper(1);\n"
            "    println!(\"{}\", y);\n"
            "    io::stdout().flush();\n"
            "}\n"
        )
        r = engine.detect_undefined_symbols(src, "rs")
        self.assertEqual(r["suspects"], [])

    def test_java_catches_hallucinated_call(self):
        src = "class A {\n    void run() { ghost(); }\n}\n"
        r = engine.detect_undefined_symbols(src, "java")
        self.assertIn("ghost", r["suspects"])

    def test_java_clean_methods_fields_and_imports(self):
        src = (
            "import java.util.List;\n"
            "class Calc {\n"
            "    private int count = 0;\n"
            "    int add(int a, int b) { return a + b; }\n"
            "    void run() { System.out.println(add(1, 2)); }\n"
            "}\n"
        )
        r = engine.detect_undefined_symbols(src, "java")
        self.assertEqual(r["suspects"], [])

    def test_c_catches_hallucinated_call(self):
        src = "int main(void) { ghost(); return 0; }\n"
        r = engine.detect_undefined_symbols(src, "c")
        self.assertIn("ghost", r["suspects"])

    def test_c_clean_with_libc_and_defs(self):
        src = (
            "#include <stdio.h>\n"
            "int add(int a, int b) { return a + b; }\n"
            "int main(void) { printf(\"%d\", add(1, 2)); return 0; }\n"
        )
        r = engine.detect_undefined_symbols(src, "c")
        self.assertEqual(r["suspects"], [])

    def test_cpp_clean_class_vars_and_fields(self):
        src = (
            "#include <vector>\n"
            "#include <string>\n"
            "class Box {\n"
            "public:\n"
            "    Box(int s) : size(s) {}\n"
            "    int get() const { return size; }\n"
            "private:\n"
            "    int size;\n"
            "};\n"
            "int main() { Box b(3); std::string s = \"x\"; return b.get(); }\n"
        )
        r = engine.detect_undefined_symbols(src, "cpp")
        self.assertEqual(r["suspects"], [])

    def test_cpp_catches_hallucinated_call(self):
        src = "int main() { ghost(); return 0; }\n"
        r = engine.detect_undefined_symbols(src, "c++")
        self.assertIn("ghost", r["suspects"])

    def test_csharp_catches_hallucinated_call(self):
        src = "using System;\nclass P { static void Main() { Ghost(); } }\n"
        r = engine.detect_undefined_symbols(src, "csharp")
        self.assertIn("Ghost", r["suspects"])

    def test_csharp_clean_console_call(self):
        src = 'using System;\nclass P { static void Main() { Console.WriteLine("hi"); } }\n'
        r = engine.detect_undefined_symbols(src, "c#")
        self.assertEqual(r["suspects"], [])

    def test_php_catches_hallucinated_call(self):
        src = "<?php\nfunction run() { ghost(); }\nrun();\n"
        r = engine.detect_undefined_symbols(src, "php")
        self.assertIn("ghost", r["suspects"])

    def test_php_clean_vars_and_functions(self):
        src = (
            "<?php\n"
            "function add($a, $b) { return $a + $b; }\n"
            "$x = 1;\n"
            "$y = add($x, 2);\n"
            "echo $y;\n"
        )
        r = engine.detect_undefined_symbols(src, "php")
        self.assertEqual(r["suspects"], [])

    def test_ruby_catches_hallucinated_call(self):
        src = "def run\n  ghost\nend\nrun\n"
        r = engine.detect_undefined_symbols(src, "ruby")
        self.assertIn("ghost", r["suspects"])

    def test_ruby_clean(self):
        src = "def helper(x)\n  x * 2\nend\nputs helper(21)\n"
        r = engine.detect_undefined_symbols(src, "rb")
        self.assertEqual(r["suspects"], [])

    def test_kotlin_catches_hallucinated_call(self):
        src = "fun main() {\n    ghost()\n}\n"
        r = engine.detect_undefined_symbols(src, "kotlin")
        self.assertIn("ghost", r["suspects"])

    def test_kotlin_clean_import_and_lambdas(self):
        src = (
            "import kotlin.math.sqrt\n"
            "fun main() {\n"
            "    val x = 4\n"
            "    println(sqrt(x.toDouble()))\n"
            "}\n"
        )
        r = engine.detect_undefined_symbols(src, "kt")
        self.assertEqual(r["suspects"], [])

    def test_swift_catches_hallucinated_call(self):
        src = "func run() {\n    ghost()\n}\n"
        r = engine.detect_undefined_symbols(src, "swift")
        self.assertIn("ghost", r["suspects"])

    def test_swift_clean(self):
        src = (
            "import Foundation\n"
            "func helper(_ x: Int) -> Int { x + 1 }\n"
            "let y = helper(1)\n"
            "print(y)\n"
        )
        r = engine.detect_undefined_symbols(src, "swift")
        self.assertEqual(r["suspects"], [])

    def test_dart_catches_hallucinated_call(self):
        src = "void main() {\n    ghost();\n}\n"
        r = engine.detect_undefined_symbols(src, "dart")
        self.assertIn("ghost", r["suspects"])

    def test_dart_clean_methods(self):
        src = (
            "class Calc {\n"
            "  int add(int a, int b) { return a + b; }\n"
            "}\n"
            "void main() { print(Calc().add(1, 2)); }\n"
        )
        r = engine.detect_undefined_symbols(src, "dart")
        self.assertEqual(r["suspects"], [])

    def test_lua_catches_hallucinated_call(self):
        src = "function run() ghost() end\n"
        r = engine.detect_undefined_symbols(src, "lua")
        self.assertIn("ghost", r["suspects"])

    def test_lua_clean_locals_and_calls(self):
        src = "local function helper(x) return x * 2 end\nfunction run() print(helper(21)) end\n"
        r = engine.detect_undefined_symbols(src, "lua")
        self.assertEqual(r["suspects"], [])

    def test_r_catches_hallucinated_call(self):
        src = "run <- function() { ghost() }\n"
        r = engine.detect_undefined_symbols(src, "r")
        self.assertIn("ghost", r["suspects"])

    def test_r_clean_assignment_and_call(self):
        src = "helper <- function(x) x * 2\nprint(helper(21))\n"
        r = engine.detect_undefined_symbols(src, "r")
        self.assertEqual(r["suspects"], [])

    def test_zig_catches_hallucinated_call(self):
        src = "fn main() {\n    ghost();\n}\n"
        r = engine.detect_undefined_symbols(src, "zig")
        self.assertIn("ghost", r["suspects"])

    def test_zig_clean_import_and_functions(self):
        src = (
            'const std = @import("std");\n'
            "fn helper(x: i32) i32 { return x + 1; }\n"
            "pub fn main() { std.debug.print(\"{d}\", .{helper(1)}); }\n"
        )
        r = engine.detect_undefined_symbols(src, "zig")
        self.assertEqual(r["suspects"], [])

    def test_unsupported_language_reports_note(self):
        r = engine.detect_undefined_symbols("print('x')", "brainfuck")
        self.assertEqual(r["suspects"], [])
        self.assertIn("Unsupported", r["note"])
        self.assertIn("go", r["note"])


class TestStreamedSandbox(unittest.TestCase):
    def test_large_output_kept_bounded_tail(self):
        # 100k chars then a marker: memory must stay bounded AND the tail
        # (last 8000 chars) must survive — the marker proves tail semantics.
        src = "import sys\nprint('X' * 100000)\nprint('TAIL_MARKER')\n"
        r = engine.sandbox_run([PY, "-c", src], 15)
        self.assertTrue(r["stdout"].rstrip().endswith("TAIL_MARKER"), repr(r["stdout"][-80:]))
        self.assertLessEqual(len(r["stdout"]), 8000)

    def test_clean_output_unaffected(self):
        r = engine.sandbox_run([PY, "-c", "print(6*7)"], 10)
        self.assertIn("42", r["stdout"])


class TestCheckContract(unittest.TestCase):
    def test_requires_missing_fails(self):
        r = engine.check_contract(
            "def run():\n    return 1\n", '{"requires": ["run", "ghost"]}'
        )
        self.assertFalse(r["contract_ok"])
        self.assertEqual(r["missing"], ["ghost"])

    def test_requires_satisfied_passes(self):
        r = engine.check_contract(
            "def run():\n    return helper()\ndef helper():\n    return 1\n",
            '{"requires": ["run", "helper"]}',
        )
        self.assertTrue(r["contract_ok"])
        self.assertEqual(r["missing"], [])

    def test_prohibits_token_hit(self):
        r = engine.check_contract(
            "def run():\n    return 1  # TODO\n", '{"prohibits": ["TODO"]}'
        )
        self.assertFalse(r["contract_ok"])
        self.assertEqual(r["prohibited_hits"], ["TODO"])

    def test_prohibits_clean(self):
        r = engine.check_contract("def run():\n    return 1\n", '{"prohibits": ["TODO"]}')
        self.assertTrue(r["contract_ok"])

    def test_invalid_contract_json(self):
        r = engine.check_contract("x = 1\n", "not json")
        self.assertFalse(r["contract_ok"])
        self.assertIn("invalid", r["note"])

    def test_go_contract_uses_registry_definitions(self):
        r = engine.check_contract(
            "package main\nfunc helper(x int) int { return x }\n",
            '{"requires": ["helper"]}',
            "go",
        )
        self.assertTrue(r["contract_ok"])

    def test_defined_symbols_public_helper(self):
        ds = engine.defined_symbols(
            "package main\nfunc helper(x int) int { return x }\n", "go"
        )
        self.assertIn("helper", ds)


class TestExportPromptPool(unittest.TestCase):
    def test_parse_and_render_deterministic(self):
        sys.path.insert(0, os.path.join(PLUGIN_ROOT, "scripts"))
        import export_prompt_pool as xp

        pool = os.path.join(
            PLUGIN_ROOT, "skills", "verify-before-code", "references", "PROMPT-POOL.md"
        )
        entries = xp.parse_pool(pool)
        self.assertGreaterEqual(len(entries), 20)  # 23 entries today
        for fmt in ("claude", "agents", "cursor"):
            out = xp.render(fmt, entries)
            self.assertIn("## A1", out)
            self.assertIn("## J4", out)
            self.assertEqual(out, xp.render(fmt, entries))  # deterministic


class TestPerformanceBaseline(unittest.TestCase):
    """Regression gate: verify_code + scan_hallucination on a ~0.5 MB
    synthetic corpus must stay under 10 s (real baseline ~0.4 s). Catches a
    pathological regression without flaking on slow CI. Uses the same
    generator as ``scripts/bench.py`` so the measurement is comparable."""

    def test_half_megabyte_under_ten_seconds(self):
        import time

        scripts_dir = os.path.join(PLUGIN_ROOT, "scripts")
        sys.path.insert(0, scripts_dir)
        try:
            import bench  # noqa: PLC0415
            src = bench.make_source(0.5)
            t0 = time.perf_counter()
            engine.detect_undefined_symbols(src)
            engine.scan_hallucination_words(src)
            elapsed = time.perf_counter() - t0
        finally:
            sys.path.remove(scripts_dir)
        self.assertLess(
            elapsed, 10.0,
            f"hot path took {elapsed:.2f}s on ~0.5MB synthetic source",
        )


class TestCheckImports(unittest.TestCase):
    """Package-hallucination (slopsquatting) guard — USENIX Security 2025."""

    def test_stdlib_and_common_known_pass(self):
        src = "import os\nimport json\nimport requests\nimport numpy as np\nfrom pathlib import Path\n"
        r = engine.check_imports(src)
        self.assertTrue(r["imports_ok"])
        self.assertEqual(r["suspicious"], [])

    def test_unknown_package_flagged(self):
        src = "import os\nimport slopsquat_utils\n"
        r = engine.check_imports(src)
        self.assertFalse(r["imports_ok"])
        self.assertEqual([s["package"] for s in r["suspicious"]], ["slopsquat_utils"])

    def test_known_packages_allowlist(self):
        src = "import os\nimport mycompany_core\n"
        r = engine.check_imports(src, known_packages=["mycompany_core"])
        self.assertTrue(r["imports_ok"])

    def test_relative_imports_skipped(self):
        # from . import x / from ..pkg import y — package-local, never flagged
        src = "from . import helpers\nfrom ..db import session\nimport os\n"
        r = engine.check_imports(src)
        self.assertTrue(r["imports_ok"])

    def test_other_language_honest_empty(self):
        r = engine.check_imports("package main\nimport \"fmt\"\n", "go")
        self.assertTrue(r["imports_ok"])
        self.assertIn("python", r["note"])


class TestCheckManifest(unittest.TestCase):
    """Manifest scanning — the slopsquatting FIRST CONTACT surface."""

    def test_requirements_flags_phantom_package(self):
        text = "numpy==1.26.0\n# comment\nslopsquat-utils>=1.0\n--index-url https://pypi.org/simple\n"
        r = engine.check_manifest(text, kind="requirements")
        self.assertFalse(r["manifest_ok"])
        self.assertEqual([s["package"] for s in r["suspicious"]], ["slopsquat-utils"])
        self.assertEqual(r["dependencies_checked"], 2)

    def test_requirements_normalizes_pypi_names(self):
        text = "PyYAML==6.0\npython_dateutil>=2.8\npre_commit==3.0\n"
        r = engine.check_manifest(text, kind="requirements")
        self.assertTrue(r["manifest_ok"], r["suspicious"])

    def test_requirements_known_packages_allowlist(self):
        text = "mycompany-core==1.0\n"
        r = engine.check_manifest(text, kind="requirements", known_packages=["mycompany_core"])
        self.assertTrue(r["manifest_ok"])

    def test_pyproject_pep621_flags_phantom(self):
        text = (
            "[project]\n"
            'name = "app"\n'
            "dependencies = [\n"
            '    "requests>=2.0",\n'
            '    "uvicorn[standard]>=0.20",\n'
            '    "phantom-tomllib>=1.0",\n'
            "]\n"
        )
        r = engine.check_manifest(text, kind="pyproject")
        self.assertEqual([s["package"] for s in r["suspicious"]], ["phantom-tomllib"])
        self.assertEqual(r["dependencies_checked"], 3)

    def test_pyproject_poetry_section_flags_phantom(self):
        text = (
            "[tool.poetry.dependencies]\n"
            'python = "^3.9"\n'
            'requests = "^2.0"\n'
            'ghost-poetry-pkg = "^1.0"\n'
        )
        r = engine.check_manifest(text, kind="pyproject")
        self.assertEqual([s["package"] for s in r["suspicious"]], ["ghost-poetry-pkg"])

    def test_package_json_flags_phantom(self):
        text = (
            '{\n  "name": "app",\n  "dependencies": {\n    "express": "^4.0",\n'
            '    "@babel/core": "^7.0"\n  },\n  "devDependencies": {\n'
            '    "phantom-npm-pkg": "^1.0"\n  }\n}\n'
        )
        r = engine.check_manifest(text, kind="package.json")
        self.assertEqual([s["package"] for s in r["suspicious"]], ["phantom-npm-pkg"])
        self.assertEqual(r["dependencies_checked"], 3)

    def test_kind_inference_from_content(self):
        r = engine.check_manifest('{"dependencies": {"express": "^4.0"}}')
        self.assertEqual(r["kind"], "package.json")
        self.assertTrue(r["manifest_ok"], r["suspicious"])
        r2 = engine.check_manifest("[project]\ndependencies = [\n  \"requests>=2.0\",\n]\n")
        self.assertEqual(r2["kind"], "pyproject")
        r3 = engine.check_manifest("numpy==1.0\n")
        self.assertEqual(r3["kind"], "requirements")

    def test_unknown_kind_fails_loudly(self):
        r = engine.check_manifest("whatever", kind="cargo")
        self.assertFalse(r["manifest_ok"])
        self.assertIn("unsupported", r["note"])

    def test_preexisting_unknowns_are_not_suspects(self):
        # long-tail unknowns the project itself already depends on are the
        # project's own history; only NEWLY ADDED names are the hallucination
        # moment (diff-scoped via the CLI's git-HEAD baseline)
        text = "pytest-cov==5.0\ntrustme==1.1\nphantom-new-pkg>=1.0\n"
        r = engine.check_manifest(
            text, kind="requirements", preexisting=["pytest-cov", "trustme"]
        )
        self.assertEqual([s["package"] for s in r["suspicious"]], ["phantom-new-pkg"])
        self.assertEqual(sorted(r["preexisting_unknown"]), ["pytest-cov", "trustme"])
        self.assertFalse(r["manifest_ok"])
        self.assertIn("Diff-scoped", r["note"])

    def test_new_research_tokens_flagged(self):
        # tokens added from 2025 research (slopsquatting + overclaim/fabrication)
        r = engine.scan_hallucination_words(
            "This is bulletproof and cannot fail. The data is fictitious and non-existent."
        )
        groups = {h["group"] for h in r["hits"]}
        self.assertIn("oversold", groups)
        self.assertIn("fabricated", groups)
        r2 = engine.scan_hallucination_words("这个包是凭空捏造的，子虚乌有，绝对可靠。")
        self.assertFalse(r2["clean"])


class TestHallucinationScan(unittest.TestCase):
    def test_stub_group(self):
        r = engine.scan_hallucination_words("def run():\n    return stub_result  # TODO\n")
        self.assertFalse(r["clean"])
        groups = {h["group"] for h in r["hits"]}
        self.assertIn("stub_code", groups)

    def test_oversold_group(self):
        r = engine.scan_hallucination_words("The feature is production ready, all tests pass.")
        self.assertFalse(r["clean"])
        groups = {h["group"] for h in r["hits"]}
        self.assertIn("oversold", groups)

    def test_oversold_security_and_performance_claims(self):
        # unverified security/performance claims fire as oversold (error)
        r = engine.scan_hallucination_words(
            "No vulnerabilities, secure by design, zero downtime. 高并发下超高性能，绝对安全。"
        )
        self.assertFalse(r["clean"])
        self.assertIn("oversold", {h["group"] for h in r["hits"]})
        self.assertTrue(r["blocking"])

    def test_oversold_security_legitimate_usage_clean(self):
        # describing the act of hardening is not an unverified claim
        r = engine.scan_hallucination_words(
            "The design review fixed two issues; we optimized the query with an index.\n"
            "Encrypt the token before storing it.\n"
        )
        self.assertTrue(r["clean"], r["hits"])

    def test_fabricated_group(self):
        r = engine.scan_hallucination_words("this is a simulated example")
        self.assertFalse(r["clean"])
        groups = {h["group"] for h in r["hits"]}
        self.assertIn("fabricated", groups)

    def test_clean(self):
        r = engine.scan_hallucination_words("import os\nprint(os.getcwd())\n")
        self.assertTrue(r["clean"])

    def test_unittest_mock_not_flagged(self):
        src = "from unittest.mock import Mock\nm = Mock()\nm.fake_method.return_value = 1\n"
        r = engine.scan_hallucination_words(src)
        self.assertTrue(r["clean"], r["hits"])

    def test_dotted_path_not_flagged(self):
        r = engine.scan_hallucination_words(
            "import unittest.mock\nresult = unittest.mock.call(x)\n"
        )
        self.assertTrue(r["clean"], r["hits"])

    def test_real_stub_still_flagged(self):
        src = "def run():\n    return stub_result  # TODO: replace with real call\n"
        r = engine.scan_hallucination_words(src)
        self.assertFalse(r["clean"])

    def test_allowlist_override(self):
        src = "m = Mock()\nthis is a fake thing\n"
        strict = engine.scan_hallucination_words(src, allowlist=[])
        self.assertFalse(strict["clean"])
        relaxed = engine.scan_hallucination_words(src)
        self.assertTrue(any(h["word"] == "fake" for h in relaxed["hits"]))
        self.assertTrue(all(h["word"] != "mock" for h in relaxed["hits"]))

    def test_default_severities(self):
        src = "# TODO: later\nall tests pass, guaranteed\ndefinitely simulated\n"
        r = engine.scan_hallucination_words(src)
        sev_by_group = {h["group"]: h["severity"] for h in r["hits"]}
        self.assertEqual(sev_by_group["stub_code"], "warning")
        self.assertEqual(sev_by_group["oversold"], "error")
        self.assertEqual(sev_by_group["fabricated"], "error")
        self.assertTrue(r["blocking"])
        self.assertFalse(r["clean"])

    def test_severity_override_downgrades_to_info(self):
        src = "guaranteed to work\n"
        r = engine.scan_hallucination_words(src, severities={"oversold": "info"})
        self.assertEqual(r["hits"][0]["severity"], "info")
        self.assertFalse(r["blocking"])

    def test_warning_only_does_not_block(self):
        src = "# TODO: finish this section\n"
        r = engine.scan_hallucination_words(src)
        self.assertFalse(r["clean"])
        self.assertFalse(r["blocking"])

    def test_fabricated_url_group(self):
        # phantom squatting: placeholder stand-ins, reserved TLDs, and
        # "example" fabricated into non-reserved domains all fire
        src = (
            "docs: https://docs.example-fake-api.dev/v2\n"
            "curl https://api.yourdomain.com/ping\n"
            "endpoint = https://myapp.test/hook\n"
            "部署到你的域名即可生效。\n"
        )
        r = engine.scan_hallucination_words(src)
        url_hits = [h for h in r["hits"] if h["group"] == "fabricated_url"]
        self.assertEqual(len(url_hits), 4, url_hits)
        self.assertIn("fabricated_url", r["groups"])
        self.assertFalse(r["blocking"])  # default severity is warning

    def test_fabricated_url_reserved_and_real_domains_clean(self):
        src = (
            "clone https://github.com/Morningstar202604/AgentSeed\n"
            "docs: https://example.com/a and https://example.net and https://example.org\n"
            "https://docs.example.edu/guide and https://docs.python.org/3/\n"
        )
        r = engine.scan_hallucination_words(src)
        self.assertTrue(r["clean"], r["hits"])


class TestConformance(unittest.TestCase):
    def test_self_conformant(self):
        r = engine.check_plugin_conformance(PLUGIN_ROOT)
        self.assertTrue(r["ok"], r)

    def test_frontmatter_with_dashes_in_body(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            skill_dir = os.path.join(d, "skills", "demo-skill")
            os.makedirs(skill_dir)
            Path(skill_dir, "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: ok\n---\n\n---\nnot frontmatter\n",
                encoding="utf-8",
            )
            # body containing a '---' line must not corrupt the parse
            r = engine.check_plugin_conformance(d)
            self.assertEqual([e for e in r["errors"] if "demo-skill" in e], [], r["errors"])

    def test_rejects_bad_repository_type(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            Path(d, "plugin.json").write_text(
                '{"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",'
                '"name":"badplugin","repository":{"type":"git","url":"x"}}',
                encoding="utf-8",
            )
            r = engine.check_plugin_conformance(d)
            self.assertFalse(r["ok"])
            self.assertTrue(any("repository" in e for e in r["errors"]))

    @staticmethod
    def _write_plugin(tmp, plugin_json, mcp_json):
        Path(tmp, "plugin.json").write_text(plugin_json, encoding="utf-8")
        Path(tmp, "mcp.json").write_text(mcp_json, encoding="utf-8")

    PJ = '{"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json","name":"t"}'
    MJ = (
        '{"$schema":"https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",'
        '"mcpServers":{"s":%s}}'
    )

    def test_mcp_unknown_field_in_variant(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            # 'url' belongs to the http variants, not stdio
            self._write_plugin(
                d, self.PJ, self.MJ % '{"type":"stdio","command":"srv","url":"https://x"}'
            )
            r = engine.check_plugin_conformance(d)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unknown field 'url'" in e for e in r["errors"]))

    def test_mcp_reserved_env_keys(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(
                d, self.PJ, self.MJ % '{"type":"stdio","command":"srv","env":{"PLUGIN_DATA":"/x"}}'
            )
            r = engine.check_plugin_conformance(d)
            self.assertFalse(r["ok"])
            self.assertTrue(any("reserved" in e for e in r["errors"]))

    def test_mcp_http_non_loopback_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(
                d, self.PJ, self.MJ % '{"type":"streamable-http","url":"http://example.com/mcp"}'
            )
            r = engine.check_plugin_conformance(d)
            self.assertFalse(r["ok"])
            self.assertTrue(any("HTTPS" in e for e in r["errors"]))

    def test_mcp_loopback_http_allowed_and_fragment_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(
                d, self.PJ, self.MJ % '{"type":"sse","url":"http://localhost:3000/sse#frag"}'
            )
            r = engine.check_plugin_conformance(d)
            self.assertFalse(r["ok"])
            self.assertFalse(any("HTTPS" in e for e in r["errors"]))
            self.assertTrue(any("fragment" in e for e in r["errors"]))

    def test_mcp_valid_remote_entry_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(
                d,
                self.PJ,
                self.MJ % '{"type":"streamable-http","url":"https://api.example.com/mcp",'
                '"headers":{"X-Tenant":"public"}}',
            )
            r = engine.check_plugin_conformance(d)
            self.assertEqual([e for e in r["errors"] if "mcp.json" in e], [], r["errors"])


class TestSandboxRun(unittest.TestCase):
    def test_runs_command(self):
        r = engine.sandbox_run([PY, "-c", "print(6*7)"], 10)
        self.assertEqual(r["exit_code"], 0)
        self.assertIn("42", r["stdout"])

    def test_timeout_safety(self):
        r = engine.sandbox_run([PY, "-c", "import time; time.sleep(30)"], 1)
        self.assertTrue(r["timed_out"])


class TestSchemaValidate(unittest.TestCase):
    def test_valid(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        r = engine.schema_validate({"name": "agentseed"}, schema)
        self.assertTrue(r["valid"])

    def test_invalid(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        r = engine.schema_validate({"name": 123}, schema)
        self.assertFalse(r["valid"])
        self.assertTrue(any("type" in e for e in r["errors"]))

    def test_required_without_properties(self):
        schema = {"type": "object", "required": ["name"]}
        r = engine.schema_validate({}, schema)
        self.assertFalse(r["valid"])
        self.assertTrue(any("name" in e for e in r["errors"]))

    def test_oversized_pattern_rejected_both_paths(self):
        from engine import schema as schema_mod

        evil = "a" * 300
        r = schema_mod.schema_validate("x", {"type": "string", "pattern": evil})
        self.assertFalse(r["valid"])
        self.assertIn("ReDoS", r["errors"][0])
        # nested occurrence is caught too (jsonschema path compiles lazily)
        r2 = schema_mod.schema_validate(
            {"s": "x"}, {"type": "object", "properties": {"s": {"pattern": evil}}}
        )
        self.assertFalse(r2["valid"])
        # boundary: 256 chars still validates normally
        ok_pattern = "^" + "a" * 254 + "$"
        r3 = schema_mod.schema_validate("a" * 254, {"type": "string", "pattern": ok_pattern})
        self.assertTrue(r3["valid"], r3)

    def test_const_null_validated(self):
        r = engine.schema_validate(None, {"const": None})
        self.assertTrue(r["valid"])
        r = engine.schema_validate("x", {"const": None})
        self.assertFalse(r["valid"])

    def test_enum_bool_not_equal_int(self):
        r = engine.schema_validate(False, {"enum": [0]})
        self.assertFalse(r["valid"])
        r = engine.schema_validate(True, {"enum": [1]})
        self.assertFalse(r["valid"])
        r = engine.schema_validate(0, {"enum": [0]})
        self.assertTrue(r["valid"])

    def test_type_array(self):
        schema = {"type": ["string", "null"]}
        self.assertTrue(engine.schema_validate(None, schema)["valid"])
        self.assertTrue(engine.schema_validate("s", schema)["valid"])
        r = engine.schema_validate(5, schema)
        self.assertFalse(r["valid"])
        self.assertTrue(any("type" in e for e in r["errors"]))


class TestConfig(unittest.TestCase):
    def test_load_config_missing_returns_empty(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                self.assertEqual(engine.load_config(), {})
            finally:
                os.chdir(old)

    def test_load_config_plugin_data(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, engine.CONFIG_FILENAME)
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('{"severities": {"stub_code": "info"}, "timeout": 15}')
            env = {k: v for k, v in os.environ.items() if k not in ("AGENTSEED_CONFIG",)}
            env["PLUGIN_DATA"] = d
            import subprocess

            out = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import json, sys; sys.path.insert(0, r'%s');"
                    "import guard_engine as e; print(json.dumps(e.load_config()))"
                    % os.path.dirname(os.path.abspath(__file__)),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=True,
            )
            self.assertEqual(json.loads(out.stdout)["timeout"], 15)

    def test_load_config_invalid_json_ignored(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            self.assertEqual(engine.load_config(bad), {})


class TestSchemaDraft07Tuples(unittest.TestCase):
    """draft-07 tuple 'items' must validate, not crash (regression)."""

    def test_tuple_items_via_jsonschema_fallback(self):
        from engine import schema as schema_mod

        r = schema_mod.schema_validate(
            [1, "a"], {"items": [{"type": "integer"}, {"type": "string"}]}
        )
        self.assertTrue(r["valid"], r)
        self.assertNotIn("crashed", "".join(r["errors"]))

    def test_bad_tuple_types_detected(self):
        from engine import schema as schema_mod

        r = schema_mod.schema_validate(
            ["x", 1], {"items": [{"type": "integer"}, {"type": "string"}]}
        )
        self.assertFalse(r["valid"])
        self.assertEqual(len(r["errors"]), 2)

    def test_additional_items_false(self):
        from engine import schema as schema_mod

        r = schema_mod.schema_validate(
            [1, "a", True],
            {"items": [{"type": "integer"}, {"type": "string"}], "additionalItems": False},
        )
        self.assertFalse(r["valid"])


class TestMatchGuardsForOldPythons(unittest.TestCase):
    """ast.Match* guards must keep 3.9 alive (no AttributeError)."""

    def test_detection_runs_with_match_nodes_absent(self):
        from engine import symbols as sym

        saved = (sym._MATCH_AS, sym._MATCH_STAR, sym._MATCH_MAPPING)
        sym._MATCH_AS = sym._MATCH_STAR = sym._MATCH_MAPPING = None
        try:
            r = sym.detect_undefined_symbols("match x:\n    case [a]:\n        f(a)\n")
        finally:
            sym._MATCH_AS, sym._MATCH_STAR, sym._MATCH_MAPPING = saved
        if sys.version_info >= (3, 10):
            # Nodes exist but were disabled: parse succeeds, guard degrades
            # gracefully and the real suspect is still reported.
            self.assertIn("f", r["suspects"])
        else:
            # Real pre-3.9 parser: match syntax is a SyntaxError; the engine
            # must degrade to an empty (non-crashing) result.
            self.assertEqual(r["suspects"], [])


class TestPyflakesMerge(unittest.TestCase):
    """Del-context undefined names are caught by the stdlib walk itself
    (ast.Delete targets); when pyflakes is installed its findings merge in
    as additional scope-aware coverage."""

    def test_del_undefined_name_caught_regardless_of_pyflakes(self):
        from engine import symbols as sym

        r = sym.detect_undefined_symbols("def f():\n    del ghost_var\n")
        self.assertIn("ghost_var", r["suspects"], r)
        if sym._HAS_PYFLAKES:
            self.assertIn("pyflakes", r["note"])


class TestPluginVersionFallback(unittest.TestCase):
    """version.py must degrade to '0.0.0' when its root has no/broken
    plugin.json. Executed from a COPY so the __file__-derived root is tmpdir."""

    @staticmethod
    def _run_copy(source_path: str, fake_file: str) -> str:
        import subprocess

        script = (
            "ns = {'__file__': %r, '__name__': 'v_under_test'}\n"
            "code = open(%r, encoding='utf-8').read()\n"
            "exec(compile(code, %r, 'exec'), ns)\n"
            "print(ns['plugin_version']())\n" % (fake_file, source_path, source_path)
        )
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return out.stdout.strip()

    def test_missing_and_broken_manifests_fall_back(self):
        import tempfile

        from engine import version as vmod

        self.assertTrue(vmod.plugin_version().count(".") >= 1)  # sanity: real path works
        source_path = os.path.abspath(vmod.__file__)

        with tempfile.TemporaryDirectory() as d:
            fake_file = os.path.join(d, "engine", "version.py")
            os.makedirs(os.path.dirname(fake_file))
            # broken plugin.json -> fallback
            with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as fh:
                fh.write("{not json")
            self.assertEqual(self._run_copy(source_path, fake_file), "0.0.0")
            # missing plugin.json -> fallback
            os.remove(os.path.join(d, "plugin.json"))
            self.assertEqual(self._run_copy(source_path, fake_file), "0.0.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
