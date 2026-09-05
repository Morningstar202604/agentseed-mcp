---
description: Verify changed files with the AgentSeed tools and report evidence. / 用 AgentSeed 工具验证本次改动并给出证据报告。
argument-hint: "[文件或目录，默认本次改动 | files, default: changes]"
---

Verify the current changes with the AgentSeed tools, in this order:

1. Determine the target files: `${ARGUMENTS}`, or the files changed in this
   session, or `git diff --name-only HEAD` when inside a git repository.
2. For each source file call the agentseed MCP tools (fall back to
   `guard_cli.py verify/scan` via shell when MCP is unavailable):
   - `verify_code(source=..., language=...)` — hallucinated/undefined symbols.
   - `scan_hallucination(source=...)` — stub/oversold/fabricated/
     fabricated_url signals with severities.
3. For claims that need execution (tests pass, linter clean) use
   `sandbox_run` with `expected_exit` / `expect_output`, and cite the exit
   code + output.
4. When dependencies were added, call `check_imports` with the manifest text
   (`manifest` / `manifest_kind` arguments).
5. Persist the evidence with `record_verification(task, checks, files)` so
   the gate's coverage stage can see what was verified.

Report format: one line per file — pass/blocked, suspects, blocking hits,
and the exact evidence (commands + exit codes). Never claim completion while
any blocking finding remains. / 存在阻断性发现时不得宣称完成。
