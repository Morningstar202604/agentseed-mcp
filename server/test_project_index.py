"""0.4.0 feature tests: cross-file project index, did-you-mean suggestions,
the `init` onboarding command, and the suppress/allow noise-decay loop."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

import guard_engine as engine

from engine.index import build_index, find_project_root, symbol_map, verify_in_project

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "guard_cli.py")
PLUGIN_ROOT = os.path.dirname(HERE)
PY = sys.executable


def run_cli(*argv, cwd=None):
    return subprocess.run(
        [PY, CLI, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=cwd,
    )


def _write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _make_project() -> tempfile.TemporaryDirectory:
    d = tempfile.TemporaryDirectory()
    root = os.path.join(d.name, "proj")
    os.makedirs(root)
    _write(os.path.join(root, ".gitkeep"), "")  # any file; marker added below
    _write(os.path.join(root, ".agentseed-marker"), "")  # not a marker; use git dir
    os.makedirs(os.path.join(root, ".git"))
    return d


class TestProjectIndex(unittest.TestCase):
    def test_root_detection_walks_up_to_markers(self):
        with _make_project() as d:
            root = os.path.join(d, "proj")
            nested = _write(os.path.join(root, "pkg", "sub", "m.py"), "x = 1\n")
            self.assertEqual(find_project_root(nested), root)
            self.assertIsNone(find_project_root(d))  # above the project

    def test_index_builds_and_caches_incrementally(self):
        with _make_project() as d:
            root = os.path.join(d, "proj")
            _write(os.path.join(root, "utils.py"), "def helper():\n    return 1\n")
            first = build_index(root)
            self.assertEqual(first["stats"]["rescanned"], 1)
            second = build_index(root)
            self.assertEqual(second["stats"]["cached"], 1)
            self.assertEqual(second["stats"]["rescanned"], 0)
            self.assertIn("helper", symbol_map(second))

    def test_differential_judgment_splits_the_two_verdicts(self):
        with _make_project() as d:
            root = os.path.join(d, "proj")
            _write(os.path.join(root, "utils.py"), "def helper():\n    return 1\n")
            src = "def main():\n    return helper() + ghost_thing()\n"
            res = verify_in_project(src, "python", root)
            self.assertEqual(res["suspects"], ["ghost_thing"])
            self.assertEqual([m["name"] for m in res["missing_imports"]], ["helper"])
            self.assertEqual(
                res["missing_imports"][0]["defined_in"], ["utils.py"]
            )
            # did-you-mean works against the project pool
            res2 = verify_in_project("def main():\n    return hellper()\n", "python", root)
            self.assertEqual(res2["suspects"], ["hellper"])
            self.assertIn("helper", res2["suspects_detail"][0]["suggestions"])

    def test_outside_a_project_behavior_is_unchanged(self):
        src = "def main():\n    return helper()\n"
        res = engine.detect_undefined_symbols(src)
        self.assertEqual(res["suspects"], ["helper"])
        self.assertNotIn("missing_imports", res)

    def test_resolve_symbols_judges_before_the_call_is_written(self):
        with _make_project() as d:
            root = os.path.join(d, "proj")
            _write(os.path.join(root, "utils.py"), "def helper():\n    return 1\n")
            r = engine.resolve_symbols(["helper", "numpy", "hellper", "ghost_api"], root)
            by = {x["name"]: x for x in r["results"]}
            # project-defined: exists with defining file
            self.assertTrue(by["helper"]["exists"])
            self.assertEqual(by["helper"]["defined_in"], ["utils.py"])
            # stdlib/known package: importable without a project definition
            self.assertFalse(by["numpy"]["exists"])
            self.assertTrue(by["numpy"]["stdlib_or_known_package"])
            # typo: not project-defined, but did-you-mean points at the real one
            self.assertFalse(by["hellper"]["exists"])
            self.assertIn("helper", by["hellper"]["suggestions"])
            # fabricated: nowhere, nothing close
            self.assertFalse(by["ghost_api"]["exists"])
            self.assertFalse(by["ghost_api"]["stdlib_or_known_package"])
            self.assertFalse(r["all_found"])

    def test_resolve_symbols_dedupes_and_handles_empty(self):
        with _make_project() as d:
            root = os.path.join(d, "proj")
            _write(os.path.join(root, "utils.py"), "def helper():\n    return 1\n")
            r = engine.resolve_symbols(["helper", " helper ", ""], root)
            self.assertEqual([x["name"] for x in r["results"]], ["helper"])
            empty = engine.resolve_symbols([], root)
            self.assertEqual(empty["results"], [])
            self.assertFalse(empty["all_found"])

    def test_plain_detect_carries_did_you_mean(self):
        res = engine.detect_undefined_symbols("def f():\n    return prinnt()\n")
        self.assertIn("prinnt", res["suspects"])
        self.assertIn("print", res["suspects_detail"][0]["suggestions"])

    def test_verify_file_builtin_reports_missing_imports(self):
        with _make_project() as d:
            root = os.path.join(d, "proj")
            _write(os.path.join(root, "utils.py"), "def helper():\n    return 1\n")
            caller = _write(
                os.path.join(root, "app.py"), "def main():\n    return helper()\n"
            )
            import guard_server

            res = guard_server._execute(
                "verify_file", {"path": caller, "engine": "builtin"}
            )
            self.assertEqual(res["suspects"], [])
            self.assertEqual([m["name"] for m in res["missing_imports"]], ["helper"])


class TestInitCommand(unittest.TestCase):
    def test_init_wires_a_project_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "myapp")
            os.makedirs(root)
            r1 = run_cli("init", "--root", root)
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            payload = json.loads(r1.stdout[r1.stdout.rindex('{\n  "ok"'):])
            self.assertIn("agentseed.config.json", payload["created"])
            self.assertTrue(
                os.path.isfile(os.path.join(root, ".github", "workflows", "agentseed.yml"))
            )
            self.assertIn("mcp_json", payload["wire_your_client"])
            self.assertTrue(
                payload["wire_your_client"]["mcp_json"]["agentseed"]["args"][0].endswith(
                    "guard_server.py"
                )
            )
            # second run: nothing overwritten, gate already enforced
            r2 = run_cli("init", "--root", root)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            p2 = json.loads(r2.stdout[r2.stdout.rindex('{\n  "ok"'):])
            self.assertEqual(p2["created"], [])
            self.assertTrue(all("exists" in s for s in p2["skipped"]))
            self.assertTrue(os.path.isfile(os.path.join(root, "baseline-scan.json")))

    def test_init_rejects_missing_root(self):
        r = run_cli("init", "--root", os.path.join(tempfile.gettempdir(), "no-such-root-xyz"))
        self.assertEqual(r.returncode, 2)


class TestNoiseDecayLoop(unittest.TestCase):
    def test_suppress_and_allow_write_and_take_effect(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _write(os.path.join(d, "agentseed.config.json"), "{}\n")
            r1 = run_cli("suppress", "magic_legacy", "--config", cfg)
            self.assertEqual(r1.returncode, 0, r1.stdout)
            r2 = run_cli("allow", "works-on-my-machine", "--config", cfg)
            self.assertEqual(r2.returncode, 0, r2.stdout)
            with open(cfg, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["suppress_symbols"], ["magic_legacy"])
            self.assertEqual(data["extra_allowlist"], ["works-on-my-machine"])
            # repeat runs are idempotent, not duplicated
            run_cli("suppress", "magic_legacy", "--config", cfg)
            with open(cfg, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["suppress_symbols"].count("magic_legacy"), 1)

    def test_allow_merges_after_built_in_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _write(os.path.join(d, "c.json"), json.dumps({"extra_allowlist": ["foobaz"]}))
            allowlist = engine.merge_allowlist(None, engine.config_str_list(
                json.load(open(cfg, encoding="utf-8")), "extra_allowlist"
            ))
            self.assertIn("Mock(", allowlist)  # built-in defaults survived
            self.assertIn("foobaz", allowlist)
            res = engine.scan_hallucination_words("x = foobaz + 1\n", allowlist)
            self.assertTrue(res["clean"])

    def test_broken_config_fails_loudly_and_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _write(os.path.join(d, "c.json"), "{broken")
            r = run_cli("suppress", "x", "--config", cfg)
            self.assertEqual(r.returncode, 1)
            self.assertIn("cannot parse", r.stdout)
            with open(cfg, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "{broken")

    def test_suppressed_symbol_is_reported_not_erased(self):
        res = engine.detect_undefined_symbols(
            "def f():\n    return legacy_fn()\n", "python", suppress=["legacy_fn"]
        )
        self.assertEqual(res["suspects"], [])
        self.assertEqual(res["suppressed"], ["legacy_fn"])


class TestGateWithIndex(unittest.TestCase):
    def test_gate_reports_missing_imports_as_failures(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "utils.py"), "def helper():\n    return 1\n")
            _write(os.path.join(d, "app.py"), "def main():\n    return helper()\n")
            r = run_cli("gate", "--root", d)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            marker = '{\n  "root"'
            summary = json.loads(r.stdout[r.stdout.rindex(marker):])
            self.assertEqual(summary["checks"]["symbols"]["status"], "fail")
            self.assertEqual(
                summary["checks"]["symbols"]["missing_imports"],
                {"app.py": ["helper"]},
            )

    def test_gate_index_can_be_disabled_by_config(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "utils.py"), "def helper():\n    return 1\n")
            _write(os.path.join(d, "app.py"), "def main():\n    return helper()\n")
            _write(os.path.join(d, "agentseed.config.json"), json.dumps({"project_index": False}))
            r = run_cli("gate", "--root", d)
            marker = '{\n  "root"'
            summary = json.loads(r.stdout[r.stdout.rindex(marker):])
            # without the index the call is a plain (single-file) suspect
            self.assertEqual(summary["checks"]["symbols"]["suspects"], {"app.py": ["helper"]})
            self.assertEqual(summary["checks"]["symbols"]["missing_imports"], {})


if __name__ == "__main__":
    unittest.main()
