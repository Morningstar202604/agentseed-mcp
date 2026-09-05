---
description: Run the AgentSeed CI-equivalent gate on this repo and interpret the four stages. / 在当前仓库运行 AgentSeed 门禁并解读四阶段结果。
argument-hint: "[仓库根目录 | repo root]"
---

Run the AgentSeed gate (CI-equivalent hard check) against `${ARGUMENTS:-.}`:

```bash
python <agentseed-plugin-root>/server/guard_cli.py gate --root ${ARGUMENTS:-.}
```

Locate `<agentseed-plugin-root>` in this order: the `AGENTSEED_PLUGIN_ROOT`
environment variable → a `.agentseed-plugin-root` file next to the
verify-before-code skill → walk up from the skill directory until a directory
contains both `plugin.json` and `server/guard_cli.py` → fall back to
`~/.agentseed/AgentSeed`.

Interpret each stage for the user:

- **conformance** — Agent Plugins 1.0.0 packaging linter (skipped on
  non-plugin roots).
- **symbols** — undefined/hallucinated symbols over every Python file
  (`suspects` = likely fabricated APIs; `missing_imports` = defined elsewhere,
  import needed; `unparseable` = syntax errors).
- **scan** — hallucination signals vs the frozen baseline; only NEW signals
  fail. A missing baseline is created on first run and passes by design.
- **coverage** — changed-but-never-verified files (report only unless
  `--coverage-strict`); evidence comes from `record_verification(files=...)`.

Suggested fixes per failure: symbols → import/define/replace the suspect;
scan → fix the flagged lines or `scan --update-baseline` after deliberate
review; coverage → run the verification tools, then `record --file <path>`.
Never mark the task complete while the gate exits 1. / 门禁退出码为 1 时不得
宣称任务完成。
