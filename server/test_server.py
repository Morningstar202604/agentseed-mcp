"""AgentSeed MCP server protocol tests (spawns the real stdio server)."""

import json
import os
import subprocess
import sys
import unittest

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_server.py")

# plugin.json is the single source of truth for the server version
# (guard_server reads it via engine.plugin_version at startup).
with open(os.path.join(os.path.dirname(SERVER), "..", "plugin.json"), encoding="utf-8") as _fh:
    EXPECTED_VERSION = json.load(_fh)["version"]


class TestServerProtocol(unittest.TestCase):
    proc: subprocess.Popen

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    @classmethod
    def tearDownClass(cls):
        proc = cls.proc
        if proc.poll() is None:
            # close stdin first so the server's line-read loop hits EOF and exits
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        # always release the pipe handles; otherwise ResourceWarning fires on GC
        for _pipe in (proc.stdin, proc.stdout, proc.stderr):
            if _pipe is not None and not _pipe.closed:
                _pipe.close()

    def _rpc(self, payload: dict) -> dict:
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        self.assertTrue(line.strip(), "server closed the stream unexpectedly")
        return json.loads(line)

    def test_initialize_reports_version(self):
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
            }
        )
        self.assertEqual(r["result"]["serverInfo"]["version"], EXPECTED_VERSION)

    def test_initialize_echoes_supported_protocol(self):
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")

    def test_initialize_falls_back_on_unknown_protocol(self):
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "initialize",
                "params": {"protocolVersion": "1999-01-01"},
            }
        )
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")

    def test_ping_returns_empty_result(self):
        r = self._rpc({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(r["result"], {})

    def test_unknown_method_is_error_32601(self):
        r = self._rpc({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
        self.assertEqual(r["error"]["code"], -32601)
        self.assertNotIn("result", r)

    def test_tools_list_and_call(self):
        r = self._rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        names = {t["name"] for t in r["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "verify_code",
                "resolve_symbol",
                "verify_file",
                "check_contract",
                "check_imports",
                "scan_hallucination",
                "check_plugin",
                "sandbox_run",
                "schema_validate",
                "record_verification",
            },
        )
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "scan_hallucination",
                    "arguments": {"source": "from unittest.mock import Mock\n"},
                },
            }
        )
        result = json.loads(r["result"]["content"][0]["text"])
        self.assertTrue(result["clean"])
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "resolve_symbol",
                    "arguments": {"names": ["zoneinfo", "detect_undefined_symbols", "magic_unknown"]},
                },
            }
        )
        result = json.loads(r["result"]["content"][0]["text"])
        by_name = {x["name"]: x for x in result["results"]}
        self.assertTrue(by_name["zoneinfo"]["stdlib_or_known_package"])
        self.assertTrue(by_name["detect_undefined_symbols"]["exists"])
        self.assertFalse(by_name["magic_unknown"]["exists"])
        self.assertFalse(by_name["magic_unknown"]["stdlib_or_known_package"])

    def test_record_verification_via_protocol(self):
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "record_verification",
                    "arguments": {
                        "task": "protocol test",
                        "checks": [{"tool": "manual", "status": "pass"}],
                    },
                },
            }
        )
        result = json.loads(r["result"]["content"][0]["text"])
        # server writes into its own PLUGIN_DATA; ok flag is what matters
        self.assertTrue(result["ok"], result)

    def test_malformed_json_line_ignored_session_continues(self):
        self.proc.stdin.write("this is definitely not json\n")
        self.proc.stdin.flush()
        r = self._rpc({"jsonrpc": "2.0", "id": 40, "method": "ping"})
        self.assertEqual(r["id"], 40)

    def test_unknown_tool_returns_is_error_result(self):
        frame = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 41,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {}},
            }
        )
        text = frame["result"]["content"][0]["text"]
        self.assertIn("Unknown tool", text)

    def test_oversized_frame_rejected_session_survives(self):
        # A >2MB line must get -32600 with null id, and the session must
        # keep serving normal requests afterwards.
        big = json.dumps(
            {"jsonrpc": "2.0", "id": 30, "method": "ping", "params": {"pad": "a" * 2_100_000}}
        )
        self.proc.stdin.write(big + "\n")
        self.proc.stdin.flush()
        frame = json.loads(self.proc.stdout.readline())
        self.assertEqual(frame["error"]["code"], -32600)
        r = self._rpc({"jsonrpc": "2.0", "id": 31, "method": "ping"})
        self.assertEqual(r["id"], 31)

    def test_async_sandbox_completes_normally(self):
        # Regression guard for the Windows stdin-inheritance deadlock:
        # spawned children must complete, never stall to their timeout.
        r = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "sandbox_run",
                    "arguments": {
                        "command": [sys.executable, "-c", "print('async-ok')"],
                        "timeout": 15,
                    },
                },
            }
        )
        result = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(result["exit_code"], 0, result)
        self.assertFalse(result["timed_out"])
        self.assertIn("async-ok", result["stdout"])

    def test_sandbox_run_is_cancellable(self):
        # start a long sleep, cancel it, verify: no result frame for id 9,
        # and the session stays alive afterwards.
        self.proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "sandbox_run",
                        "arguments": {
                            "command": [sys.executable, "-c", "import time; time.sleep(20)"],
                            "timeout": 30,
                        },
                    },
                }
            )
            + "\n"
        )
        self.proc.stdin.flush()
        import time as _t

        _t.sleep(0.6)  # let the child actually spawn
        self.proc.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}}
            )
            + "\n"
        )
        self.proc.stdin.flush()
        # FIFO discipline: if the worker wrongly emitted a result for the
        # cancelled id 9, it MUST appear before this ping's reply.
        r = self._rpc({"jsonrpc": "2.0", "id": 10, "method": "ping"})
        self.assertEqual(r["id"], 10)
        import time as _t

        _t.sleep(1.0)
        r = self._rpc({"jsonrpc": "2.0", "id": 11, "method": "ping"})
        self.assertEqual(
            r["id"], 11, "unexpected late frame for cancelled request leaked into the stream"
        )


if __name__ == "__main__":
    unittest.main()
