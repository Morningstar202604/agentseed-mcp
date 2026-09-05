"""AgentSeed feature tests: line numbers, suppress, CJK tokens,
sandbox policy, config validation, audit trail, fixtures, perf gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guard_engine as engine  # type: ignore


class TestSymbolsLineNumbersAndSuppress(unittest.TestCase):
    SOURCE = (
        "import os\n"
        "\n"
        "def a():\n"
        "    return ghost_one()\n"
        "\n"
        "def b():\n"
        "    x = ghost_two + 1\n"
        "    return x\n"
    )

    def test_suspects_detail_carries_lines(self):
        r = engine.detect_undefined_symbols(self.SOURCE)
        self.assertEqual(r["suspects"], ["ghost_one", "ghost_two"])
        lines = {d["name"]: d["line"] for d in r["suspects_detail"]}
        self.assertEqual(lines, {"ghost_one": 4, "ghost_two": 7})

    def test_suppress_filters_and_reports(self):
        r = engine.detect_undefined_symbols(self.SOURCE, suppress=["ghost_two"])
        self.assertEqual(r["suspects"], ["ghost_one"])
        self.assertEqual(r["suppressed"], ["ghost_two"])
        self.assertEqual([d["name"] for d in r["suspects_detail"]], ["ghost_one"])

    def test_no_suppress_reports_empty_list(self):
        r = engine.detect_undefined_symbols(self.SOURCE)
        self.assertEqual(r["suppressed"], [])


class TestCjkTokens(unittest.TestCase):
    def test_chinese_stub_tokens_hit_as_substrings(self):
        src = "# 占位实现，稍后补充\n# 待实现\nx = 1\n"
        r = engine.scan_hallucination_words(src)
        words = {h["word"] for h in r["hits"]}
        self.assertIn("占位", words)
        self.assertTrue(any(h["group"] == "stub_code" for h in r["hits"]))

    def test_chinese_oversold_blocks_by_default(self):
        r = engine.scan_hallucination_words("# 保证通过\n")
        self.assertTrue(r["blocking"])
        self.assertEqual(r["hits"][0]["group"], "oversold")

    def test_extra_tokens_extend_pool(self):
        base = engine.scan_hallucination_words("x = frobnicate_now()\n")
        self.assertEqual(base["hits"], [])
        ext = engine.scan_hallucination_words(
            "x = frobnicate_now()\n",
            extra_tokens={"fabricated": ["frobnicate_now"]},
        )
        self.assertEqual(len(ext["hits"]), 1)
        self.assertEqual(ext["hits"][0]["group"], "fabricated")
        self.assertTrue(ext["blocking"])  # fabricated defaults to error

    def test_extra_tokens_invalid_group_ignored(self):
        r = engine.scan_hallucination_words("x = todo()\n", extra_tokens={"nope_group": ["todo"]})
        self.assertEqual(len(r["hits"]), 1)  # builtin stub hit only


class TestSandboxAllowPolicy(unittest.TestCase):
    def test_unlisted_binary_blocked_without_running(self):
        # Never spawned: the policy gate refuses BEFORE execution (-10).
        r = engine.sandbox_run(
            ["some-unlisted-tool", "--flag"],
            allowed_prefixes=["python", "pytest"],
        )
        self.assertEqual(r["exit_code"], -10)
        self.assertIn("sandbox_allowed_prefixes", r["stderr"])

    def test_listed_basename_allowed(self):
        r = engine.sandbox_run(
            [sys.executable, "-c", "print(7)"],
            allowed_prefixes=[os.path.basename(sys.executable)],
        )
        self.assertEqual(r["exit_code"], 0)
        self.assertIn("7", r["stdout"])

    def test_none_means_unrestricted(self):
        # Cross-platform: actually runs on Linux/macOS too.
        r = engine.sandbox_run([sys.executable, "-c", "print('ok')"], allowed_prefixes=None)
        self.assertEqual(r["exit_code"], 0)


class TestSandboxExpectations(unittest.TestCase):
    """Behavioral assertions: 'the command ran' upgrades to 'it produced the
    expected result' — executional verification without a second channel."""

    def test_expectations_met(self):
        r = engine.sandbox_run(
            [sys.executable, "-c", "print('result-42')"],
            expected_exit=0,
            expect_output="result-42",
        )
        self.assertEqual(r["exit_code"], 0)
        exp = r["expectations"]
        self.assertTrue(exp["met"])
        self.assertTrue(exp["exit_met"])
        self.assertTrue(exp["output_met"])

    def test_expect_exit_mismatch(self):
        r = engine.sandbox_run(
            [sys.executable, "-c", "raise SystemExit(3)"],
            expected_exit=0,
        )
        self.assertEqual(r["exit_code"], 3)
        self.assertFalse(r["expectations"]["met"])
        self.assertFalse(r["expectations"]["exit_met"])
        self.assertIsNone(r["expectations"]["output_met"])

    def test_expect_output_matches_stderr(self):
        r = engine.sandbox_run(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom-marker')"],
            expect_output="boom-marker",
        )
        self.assertTrue(r["expectations"]["met"], r)

    def test_expect_output_missing_fails(self):
        r = engine.sandbox_run(
            [sys.executable, "-c", "print('other')"],
            expect_output="not-present-marker",
        )
        self.assertFalse(r["expectations"]["met"])
        self.assertTrue(r["expectations"]["output_met"] is False)

    def test_no_expectations_keeps_result_shape(self):
        r = engine.sandbox_run([sys.executable, "-c", "print('plain')"])
        self.assertNotIn("expectations", r)


class TestSandboxAllowPolicyHardening(unittest.TestCase):
    """Regressions for the allowlist-bypass fixes: separator-boundary
    prefix matching and PATH-resolved execution (no cwd shadowing)."""

    def test_prefix_requires_separator_boundary(self):
        from engine import sandbox as sb

        with tempfile.TemporaryDirectory() as d:
            allowed_dir = os.path.join(d, "safe")
            sibling = os.path.join(d, "safe-x")
            self.assertTrue(
                sb._matches_allowlist(os.path.join(allowed_dir, "tool.exe"), [allowed_dir])
            )
            # Without the boundary fix, prefix "d/safe" would match "d/safe-x/app.exe".
            self.assertFalse(sb._matches_allowlist(os.path.join(sibling, "app.exe"), [allowed_dir]))

    def test_bare_entry_tolerates_exe_suffix(self):
        from engine import sandbox as sb

        base = os.path.basename(sys.executable)
        stem = base[:-4] if base.lower().endswith(".exe") else base
        self.assertTrue(sb._matches_allowlist(sys.executable, [stem]))

    def test_path_qualified_sibling_entry_never_basename_matches(self):
        from engine import sandbox as sb

        with tempfile.TemporaryDirectory() as d:
            # An entry that LOOKS like a directory must not match via basename.
            entry = os.path.join(d, "tools")
            self.assertFalse(sb._matches_allowlist(os.path.join(d, "tools", "x"), ["tools"]))
            self.assertTrue(sb._matches_allowlist(os.path.join(d, "tools", "x"), [entry]))

    def test_unresolvable_allowlisted_name_is_refused_not_spawned(self):
        r = engine.sandbox_run(
            ["definitely-not-a-real-bin-xyz"],
            5,
            allowed_prefixes=["definitely-not-a-real-bin-xyz"],
        )
        self.assertEqual(r["exit_code"], -10)

    def test_cwd_planted_executable_cannot_shadow_allowlisted_basename(self):
        exe_name = os.path.basename(sys.executable)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, exe_name), "w", encoding="utf-8") as fh:
                fh.write("print('HIJACKED')\n")
            r = engine.sandbox_run(
                [exe_name, "-c", "print('clean')"],
                20,
                cwd=d,
                allowed_prefixes=[exe_name],
            )
            self.assertEqual(r["exit_code"], 0, r)
            self.assertNotIn("HIJACKED", r["stdout"])
            self.assertIn("clean", r["stdout"])

    def test_relative_command_resolves_against_cwd_not_server(self):
        # Policy-checked path must BE the executed path: a relative command
        # resolves against the run cwd, so a planted binary in the caller
        # cwd is judged where it actually lives, not where the server sits.
        from engine import sandbox as sb

        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "real")
            planted = os.path.join(d, "planted")
            os.makedirs(real)
            os.makedirs(planted)
            r = sb.sandbox_run(["./prog.exe"], 5, cwd=planted, allowed_prefixes=[real])
            self.assertEqual(r["exit_code"], -10, r)  # outside the allowed dir
            r2 = sb.sandbox_run(["./prog.exe"], 5, cwd=real, allowed_prefixes=[real])
            self.assertNotEqual(r2["exit_code"], -10, r2)  # policy passed (file absent -> -2)

    def test_env_scrub_drops_credential_like_vars(self):
        marker = "AGENTSEED_TEST_FAKE_API_TOKEN"
        os.environ[marker] = "leak-me"
        try:
            code = (
                "import os, sys; sys.stdout.write("
                f"'TOKEN-SEEN' if os.environ.get({marker!r}) else 'SCRUBBED')"
            )
            scrubbed = engine.sandbox_run([sys.executable, "-c", code], 20, env_mode="scrub")
            inherited = engine.sandbox_run([sys.executable, "-c", code], 20, env_mode="inherit")
        finally:
            os.environ.pop(marker, None)
        self.assertEqual(scrubbed["exit_code"], 0, scrubbed)
        self.assertIn("SCRUBBED", scrubbed["stdout"], scrubbed)
        self.assertIn("TOKEN-SEEN", inherited["stdout"])

    def test_timeout_reaps_grandchild(self):
        import subprocess as sp
        import time as _time

        inner = (
            "import subprocess\n"
            f"child = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "child.wait()\n"
        )
        r = engine.sandbox_run([sys.executable, "-c", inner], 2)
        self.assertTrue(r["timed_out"], r)
        gc_pid = int(r["stdout"].strip())

        if os.name == "nt":
            listing = sp.run(
                ["tasklist", "/FI", f"PID eq {gc_pid}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout.lower()
            self.assertNotIn(str(gc_pid), listing.replace(",", ""), listing)
        elif os.path.isdir("/proc"):
            # A SIGKILLed orphan can linger as a zombie until reaped; signal-0
            # probes succeed on zombies, so inspect the kernel state instead.
            def _alive(pid: int) -> bool:
                try:
                    with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                        return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
                except (FileNotFoundError, ProcessLookupError):
                    return False

            deadline = _time.monotonic() + 5.0
            while _alive(gc_pid) and _time.monotonic() < deadline:
                _time.sleep(0.2)
            self.assertFalse(_alive(gc_pid), f"grandchild {gc_pid} survived tree-kill")
        # other platforms: timed_out assertion above is the contract

    def test_cli_sandbox_policy_block_exits_nonzero(self):
        import subprocess

        here = os.path.dirname(os.path.abspath(__file__))
        cli = os.path.join(here, "guard_cli.py")
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "agentseed.config.json")
            with open(cfg, "w", encoding="utf-8") as fh:
                json.dump({"sandbox_allowed_prefixes": ["definitely-not-a-bin"]}, fh)
            env = dict(os.environ, AGENTSEED_CONFIG=cfg)
            proc = subprocess.run(
                [sys.executable, cli, "sandbox", "--", "other-unlisted-tool", "--flag"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=60,
                cwd=here,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("-10", proc.stdout)


class TestConfigUnknownKeysAndExtras(unittest.TestCase):
    def test_unknown_keys_listed(self):
        self.assertEqual(
            engine.unknown_config_keys({"allowlist": [], "alowlist": [], "wht": 1}),
            ["alowlist", "wht"],
        )
        self.assertEqual(engine.unknown_config_keys({}), [])

    def test_extra_tokens_validator(self):
        out = engine.config_extra_tokens({"extra_tokens": {"stub_code": ["待办"], "bogus": ["x"]}})
        self.assertEqual(out, {"stub_code": ["待办"]})
        self.assertIsNone(engine.config_extra_tokens({"extra_tokens": "x"}))
        self.assertIsNone(engine.config_extra_tokens({}))


class TestAuditTrail(unittest.TestCase):
    def test_record_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            r1 = engine.record_verification(
                "task A", [{"tool": "verify_code", "status": "pass"}], data_dir=d
            )
            self.assertTrue(r1["ok"])
            r2 = engine.record_verification(
                "task B",
                [
                    {"tool": "sandbox_run", "status": "fail", "summary": "boom"},
                    {"tool": "bogus", "status": "invalid-status"},
                ],
                data_dir=d,
            )
            self.assertEqual(r2["entries"], 2)
            with open(r2["path"], encoding="utf-8") as fh:
                lines = [json.loads(ln) for ln in fh if ln.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["checks"][0]["tool"], "verify_code")
            self.assertEqual(
                lines[1]["checks"], [{"tool": "sandbox_run", "status": "fail", "summary": "boom"}]
            )

    def test_record_rejects_blank_task(self):
        self.assertFalse(engine.record_verification("  ", [])["ok"])


class TestVerificationCoverage(unittest.TestCase):
    """Evidence coverage: changed files vs recorded verifications. Closes the
    self-awareness gap — a receipt freezes what you CLAIM to verify; coverage
    names what you changed but never verified."""

    @staticmethod
    def _git_repo(d: str) -> None:
        subprocess.run(
            ["git", "init", "-q"], cwd=d, capture_output=True, text=True, timeout=60
        )

    def test_changed_vs_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            self._git_repo(d)
            for name in ("a.py", "b.py"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write("x = 1\n")
            cov = engine.coverage(d)
            self.assertTrue(cov["computable"])
            self.assertEqual(sorted(cov["changed"]), ["a.py", "b.py"])
            self.assertEqual(sorted(cov["unverified"]), ["a.py", "b.py"])
            engine.record_verification(
                "task", files=["a.py"], data_dir=os.path.join(d, ".agentseed")
            )
            cov2 = engine.coverage(d)
            self.assertEqual(cov2["verified"], ["a.py"])
            self.assertEqual(cov2["unverified"], ["b.py"])

    def test_abs_path_record_matches_git_rel_path(self):
        with tempfile.TemporaryDirectory() as d:
            self._git_repo(d)
            with open(os.path.join(d, "a.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            engine.record_verification(
                "task", files=[os.path.join(d, "a.py")], data_dir=os.path.join(d, ".agentseed")
            )
            cov = engine.coverage(d)
            self.assertEqual(cov["unverified"], [])
            self.assertEqual(cov["verified"], ["a.py"])

    def test_non_git_root_is_honestly_incomputable(self):
        with tempfile.TemporaryDirectory() as d:
            cov = engine.coverage(d)
            self.assertFalse(cov["computable"])
            self.assertIn("cannot be computed", cov["note"])


class TestExampleFixtures(unittest.TestCase):
    EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "plugins")

    def test_good_plugin_conforms(self):
        r = engine.check_plugin_conformance(
            os.path.abspath(os.path.join(self.EXAMPLES, "good-plugin"))
        )
        self.assertTrue(r["ok"], r["errors"])

    def test_broken_plugin_flagged(self):
        r = engine.check_plugin_conformance(
            os.path.abspath(os.path.join(self.EXAMPLES, "broken-plugin"))
        )
        self.assertFalse(r["ok"])
        joined = " ".join(r["errors"])
        self.assertIn("Broken-Demo", joined)
        self.assertIn("privateExtra", joined)


class TestPerfBaseline(unittest.TestCase):
    """Loose gate: a pathological slowdown must not ship silently."""

    def test_1mb_source_under_30s(self):
        sys.path.insert(
            0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        )
        import bench  # noqa: PLC0415

        src = bench.make_source(1.0)
        t0 = time.perf_counter()
        engine.detect_undefined_symbols(src)
        engine.scan_hallucination_words(src)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 30.0, f"1MB baseline regressed: {elapsed:.1f}s")


class TestCliRecordAndAsyncPolicy(unittest.TestCase):
    HERE = os.path.dirname(os.path.abspath(__file__))

    def _run(self, *args: str, env_extra=None):
        import subprocess

        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, os.path.join(self.HERE, "guard_cli.py"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=self.HERE,
            env=env,
        )

    def test_cli_record_writes_log(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(
                "record",
                "fix #7",
                "--check",
                "verify_code=pass",
                "--check",
                "scan=fail",
                "--data-dir",
                d,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            log = os.path.join(d, "verification-log.jsonl")
            with open(log, encoding="utf-8") as fh:
                entries = [json.loads(ln) for ln in fh if ln.strip()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["task"], "fix #7")
            statuses = [c["status"] for c in entries[0]["checks"]]
            self.assertEqual(statuses, ["pass", "fail"])

    def test_async_sandbox_policy_blocks_via_server(self):
        import subprocess

        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "cfg.json")
            with open(cfg, "w", encoding="utf-8") as fh:
                json.dump({"sandbox_allowed_prefixes": ["only-this-bin"]}, fh)
            proc = subprocess.Popen(
                [sys.executable, "-u", os.path.join(self.HERE, "guard_server.py")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=dict(os.environ, AGENTSEED_CONFIG=cfg),
            )
            try:
                req = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "sandbox_run",
                        "arguments": {"command": ["another-unlisted-bin", "x"]},
                    },
                }
                proc.stdin.write((json.dumps(req) + "\n").encode())
                proc.stdin.flush()
                frame = json.loads(proc.stdout.readline().decode())
                text = json.loads(frame["result"]["content"][0]["text"])
                self.assertEqual(text["exit_code"], -10)
            finally:
                # kill alone leaves the process un-reaped (ResourceWarning) and
                # the stdin/stdout pipe buffers unclosed — wait() reaps it and
                # closing the pipes silences the unclosed-file warnings.
                proc.kill()
                proc.wait()
                for _pipe in (proc.stdin, proc.stdout):
                    if _pipe is not None and not _pipe.closed:
                        _pipe.close()


class TestDetectionBenchmark(unittest.TestCase):
    """Regression lock: every injected defect class must stay caught with
    zero false positives on the clean set (seeded synthetic corpus)."""

    def test_corpus_precision_and_recall_are_perfect(self):
        sys.path.insert(
            0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        )
        import bench_detection  # noqa: PLC0415

        report = bench_detection.evaluate(bench_detection.build_corpus(4, 8, seed=7))
        self.assertEqual(report["totals"]["fn"], 0, report)
        self.assertEqual(report["totals"]["fp"], 0, report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
