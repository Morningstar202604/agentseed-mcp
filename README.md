<div align="center">

<img src="docs/logo.png" width="96" alt="AgentSeed logo">

# AgentSeed

**The anti-hallucination gate for AI coding agents.**

AI agents invent APIs. They claim "all tests pass" without running anything.
They ship confident, fabricated code. **AgentSeed is the gate that stops it** —
a zero-dependency plugin that verifies code *before* it is marked done, so
"done" means *observed fact*, not self-report.

[![License](https://img.shields.io/badge/license-PolyForm_NC_1.0.0-purple)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.6.0-blue)](https://github.com/Morningstar202604/AgentSeed/releases)
[![CI](https://github.com/Morningstar202604/AgentSeed/actions/workflows/ci.yml/badge.svg)](https://github.com/Morningstar202604/AgentSeed/actions/workflows/ci.yml)
[![MCP server score](https://glama.ai/mcp/servers/Morningstar202604/AgentSeed/badges/score.svg)](https://glama.ai/mcp/servers/Morningstar202604/AgentSeed)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Morningstar202604/AgentSeed)
[![Platforms](https://img.shields.io/badge/platform-Cursor%20%7C%20VS%20Code%20%7C%20Claude%20Code%20%7C%20Copilot-blue)](https://agent-plugins.org)

**English** · [中文](./README.zh.md) · [日本語](./README.ja.md)

</div>

---

## Why you need this

LLMs hallucinate — and in code that means **invented APIs, undefined
identifiers, fake test passes, and confident overclaims**:

- **15.1%** of code hallucinations call APIs that don't exist or were never imported ([arXiv:2404.00971](https://arxiv.org/abs/2404.00971)).
- **<10%** of hallucinated code fails tests — **~90% slips past CI** ([arXiv:2404.00971](https://arxiv.org/abs/2404.00971)).
- **60%+** of model-output errors are *unverifiable* on their face (FAVA, [SoK](https://arxiv.org/abs/2502.18468)).

Prompt-only guardrails are soft: a model can *agree* to verify and then skip
it. **AgentSeed binds the instruction to a hard gate** — the evidence comes
from running code, not from the model's own word.

## What AgentSeed is — in 30 seconds

A drop-in [Agent Plugins](https://agent-plugins.org) 1.0.0 plugin
(Skill + MCP server + optional client hook + CI gate) that makes three
promises:

| Promise | How it's kept |
| --- | --- |
| **🚫 No invented APIs** | `verify_code` parses your code in **17 languages** and flags any symbol that is called but never defined or imported |
| **🚫 No fake "done"** | `scan_hallucination` catches stubs, overclaims, and fabricated claims in **English and CJK**; `sandbox_run` proves runtime claims by actually running them |
| **🚫 No skipped verification** | the Skill gates the workflow, the **client hook** reports every `Write`/`Edit` (blocks on new signals under `diff`, or on demand under `strict`), and `guard_cli gate` enforces the rules in CI with exit codes |

It also fills the two gaps the 1.0.0 spec deliberately leaves open:

| Gap in Agent Plugins 1.0.0 | AgentSeed's answer |
| --- | --- |
| No enforcement mechanism (skills are optional to follow) | `verify-before-code` skill + optional **client-enforced hook** make verification non-skippable |
| No official conformance linter | `check_plugin` is the **first strict 1.0.0 linter** — and AgentSeed passes its own linter (`ok: true`) |

## See it catch a hallucination

```python
# Your coding agent just "finished" this — it calls magic_unknown(),
# an API that doesn't exist and was never imported:

def f():
    return magic_unknown()      # ← hallucinated API

# AgentSeed, before the task can be marked done:
$ verify_code(source=..., language="python")
{
  "language": "python",
  "suspects": ["magic_unknown"]       # ← caught, blocking
}
```

```text
# And the agent's completion claim doesn't survive either:
"The feature is production ready, all tests pass. Trust me."

$ scan_hallucination(source=...)
{
  "hits": [
    {"word": "all tests pass",   "group": "oversold",  "line": 1},
    {"word": "production ready", "group": "oversold",  "line": 1},
    {"word": "trust me",         "group": "oversold",  "line": 1}
  ],
  "clean": false                        # ← caught, blocking
}
```

The verdict is **measured, not promised**: on a seeded synthetic corpus
(5 defect classes, 100 defective + 40 clean modules) AgentSeed scores
**precision 1.0 · recall 1.0** (tp=100, fp=0, fn=0) — locked in by a
regression test. Methodology and honest limits:
[docs/BENCHMARK.md](./docs/BENCHMARK.md). Real-repo field evidence:
[docs/FIELD-TEST.md](./docs/FIELD-TEST.md).

## How the gate works

1. **Before coding** — load the SDD contract and state it in one sentence.
2. **Implement** — real code only: no placeholders, no invented APIs.
3. **Before "done"** — run `verify_code` + `scan_hallucination`; prove runtime
   claims with `sandbox_run`; validate structure with `schema_validate`.
4. **Language audit** — completion reports attach evidence; overclaim
   vocabulary is banned.
5. Only when **all checks pass** may the task be marked complete.

## Quick start

**Option A — download a release (no git needed):**

```bash
# grab the latest asset from https://github.com/Morningstar202604/AgentSeed/releases
# or use the installer, which wires it into your client:
bash install.sh --client auto --hooks        # macOS / Linux
./install.ps1 -Client auto -Hooks            # Windows PowerShell
# --client: claude | opencode | cursor | manual
# --hooks / -Hooks: also register the Claude Code enforcement hook
```

**Option B — clone:**

```bash
git clone https://github.com/Morningstar202604/AgentSeed.git
```

1. **Drop** the cloned `AgentSeed/` directory into any Agent Plugins–capable client
   (Cursor, VS Code, Claude Code, Copilot…). No build, no install.
2. The client auto-discovers the `verify-before-code` skill and the
   `agentseed` MCP server from `plugin.json` + `mcp.json`.
3. **That's it.** Every coding task is now gated: contract → implement →
   verify → evidence.

**Using it on YOUR project** (the one you cloned it for) — one command:

```bash
python3 /path/to/AgentSeed/server/guard_cli.py init --root /your/project
```

That writes a starter `agentseed.config.json`, generates a CI workflow that
clones the plugin and runs the gate, runs the first gate to bootstrap the
baseline, and prints the exact MCP snippet to point your client at the
plugin — no hand-editing.

Run it standalone or gate a human PR with the same rules:

```bash
python3 server/guard_engine.py                       # self-check demo
python3 -m unittest discover -s server               # full unit-test suite
python3 server/guard_cli.py gate --root .            # composite CI gate (any repo:
                                                     #   first run bootstraps the baseline,
                                                     #   conformance skips without plugin.json)
python3 server/guard_cli.py check . --ci             # plugin conformance only
python3 server/guard_cli.py verify src/app.ts --engine auto  # toolchain verifier if installed
python3 server/guard_cli.py verify src/app.go        # language inferred from the suffix
python3 server/guard_cli.py scan src/app.py --strict # inline or file, hallucination signals
python3 server/guard_cli.py scan . --baseline baseline-scan.json  # tree sweep, new signals only
python3 server/guard_cli.py receipt "task #42" --check sandbox_run=pass --file src/app.py
python3 server/guard_cli.py plugin init my-plugin    # scaffold → validate → pack → doctor
```

> **Windows note:** `mcp.json` may only name one literal interpreter, and it
> ships `python3` (right for macOS/Linux/WSL). On Windows run
> `./install.ps1`, which rewrites `command` to `python` in the installed copy,
> or edit it by hand as `"command": "python"` with
> `"args": ["server/guard_server.py"]` — `command` is a string, the array
> belongs to `args`. `npx agentseed-mcp` needs no editing at all: the npm shim
> picks the interpreter per platform.

## The 10 MCP tools

Zero *required* dependencies — pure Python standard library; optional extras
upgrade two tools to industry-standard engines (see below).

| Tool | Catches | Technique |
| --- | --- | --- |
| `verify_code` | Invented APIs / undefined symbols | Python AST + config-driven lexical passes (17 languages) |
| `resolve_symbol` | Hallucinated APIs BEFORE the call is written | Project symbol index + stdlib/known-package lookup with did-you-mean suggestions |
| `verify_file` | The same class, on real files | Runs the project's own toolchain (ruff, pyflakes, mypy, tsc, eslint, go vet, cargo check, javac) when installed; built-in analyzer as fallback |
| `check_contract` | Code violates a written spec | requires/prohibits contract check |
| `check_imports` | Hallucinated packages (slopsquatting) | stdlib + known-packages allowlist check; `--manifest` scans requirements/pyproject/package.json and diff-scopes against git HEAD — only NEWLY ADDED names are suspects |
| `scan_hallucination` | Placeholder code, overclaims, fabricated content, phantom domains | 50+ signals in 4 groups, EN + CJK |
| `check_plugin` | Non-conformant plugin packaging | Strict 1.0.0 linter |
| `sandbox_run` | "Tests pass" without running anything; ran but the result disagrees | Deterministic execution channel + behavioral assertions (expected_exit / expect_output) |
| `schema_validate` | Invalid structured output | JSON Schema validation |
| `record_verification` | No persistent evidence trail; changed-but-unverified files | JSONL audit trail under `PLUGIN_DATA`; `files` entries feed the gate coverage stage |

### Language coverage (honest scope)

| Language | `verify_code` analysis |
| --- | --- |
| Python | full AST scope walk (+ pyflakes when installed), line numbers |
| TypeScript / JavaScript | lexical regex pass (documented false-positive classes) |
| Go · Rust · Java · C · C++ · C# · PHP · Ruby · Kotlin · Swift | config-driven generic lexical pass |
| Dart · Lua · R · Zig | config-driven generic lexical pass |
| any other language | add a `LangSpec` registry entry — no engine change |

Honest limits: attribute calls (`obj.m()`), macros, and cross-file symbols
are not analyzed; Ruby's paren-less calls are supported. For framework code
that lexical passes cannot scope (React hook destructuring, star imports),
`verify_file` upgrades the same check to a real toolchain verifier when one
is installed — see "Toolchain verifiers" below.

### Toolchain verifiers (adapters)

The built-in analyzers are deliberately zero-dependency. When your project
already has the real tools, `verify_file` runs them through the same bounded
execution channel (no shell, capped output, timeout) and reports only the
undefined-name class in the same shape:

```bash
python3 server/guard_cli.py verifiers                     # which adapters are installed
python3 server/guard_cli.py verify src/app.ts --engine auto   # tsc if present, built-in otherwise
python3 server/guard_cli.py verify src/app.py --engine builtin # force the built-in analyzer
```

| Adapter | Language | Runs |
| --- | --- | --- |
| `ruff` / `pyflakes` | Python | `ruff check --select F821` / `python -m pyflakes` |
| `tsc` | TypeScript | `tsc --noEmit` (TS2304/TS2552) |
| `eslint` | JavaScript | `no-undef` rule |
| `govet` | Go | `go vet` (`undefined:`) |
| `cargo` | Rust | `cargo check --message-format json` (E0425) |
| `mypy` | Python | `mypy --no-error-summary` (`[name-defined]`) |
| `javac` | Java | `javac -d` (`cannot find symbol`, stderr) |

`--engine auto` picks the first installed adapter and falls back to the
built-in analyzer; an explicit `--engine <name>` fails loudly when missing.

### Project symbol index (cross-file judgment)

A single file cannot say whether a symbol exists anywhere in your project —
so the built-in analyzer now consults a cached, incrementally rebuilt index
of every defined symbol across the repo and splits raw suspects into two
verdicts:

- `suspects` — defined **nowhere** in the project: high-confidence
  hallucination, with did-you-mean suggestions of the closest real names;
- `missing_imports` — defined elsewhere but not imported in this file: a
  real bug with a different fix (the defining files are listed).

Both still gate. The index lives under `.agentseed/`, never ships in an
artifact, and turns itself off with `project_index: false` in config.

### The noise-decay loop

A gate only survives if it gets quieter as you use it:

```bash
python3 server/guard_cli.py suppress legacy_helper    # verify stops flagging it (still reported in 'suppressed')
python3 server/guard_cli.py allow works-on-my-machine # scan stops flagging it (merged after built-in defaults)
python3 server/guard_cli.py baseline audit           # what is frozen, and the review loop
```

Both write your project's `agentseed.config.json` atomically and refuse to
clobber a config that fails to parse.

### It really catches other languages — live-tested

The same rule applies to every registered language: a bare call to a symbol
that is never defined is a hallucination, whatever the syntax:

```python
# Go       detect_undefined_symbols("func main() { process_data() }", "go")  -> ["process_data"]
# Rust     fn main() { let x = load_config() }        -> ["load_config"]
# Java     class A { void m() { connect_db() } }      -> ["connect_db"]
# C        int main() { ghost(); return 0; }          -> ["ghost"]
# Kotlin   fun main() { fetch_users() }               -> ["fetch_users"]
# Swift    func run() { connect() }                   -> ["connect"]
# Ruby     def run; authenticate; end                 -> ["authenticate"]
# TypeScript function run() { connectDb() }           -> ["connectDb"]
```

Verified across Go · Rust · Java · C · C++ · C# · PHP · Ruby · Kotlin ·
Swift · TypeScript · Dart · Lua · R · Zig — every language flags its
invented call, and clean code in each language reports **zero false
positives**.


## Client-enforced hook mode

Skills persuade; **hooks observe at the client boundary and block by
choice, not by accident**. Register AgentSeed as a Claude Code hook and
every `Write`/`Edit`/`MultiEdit` is scanned automatically — no prompt can
skip the scan:

```bash
python3 server/guard_hook.py register --client claude   # idempotent, merges settings
python3 server/guard_hook.py --file path/to/source.py   # scan any file directly
```

- **PreToolUse** inspects the incoming content *before* it lands on disk.
- **PostToolUse** re-checks saved files on write paths without inline content.
- **Gate profiles** (config `hook_profile`, or `--profile` on the CLI):
  | Profile | Behavior |
  | --- | --- |
  | `advisory` (default) | findings are reported (status `flagged`) and the write proceeds — evidence and visibility, zero interruption |
  | `diff` | blocks only when the edit **adds** new signals relative to the file's previous content (hook-level `--baseline`) |
  | `strict` | blocks (exit `2`) on any error-severity hit or undefined-symbol suspect, for maintainers who tuned their allowlist |
- **Failure policy (honest):** infrastructure problems (bad stdin, unreadable
  files) never block work — fail-open; under `advisory`, nothing blocks at
  all. A gate that cries wolf gets disabled; one that reports honestly gets
  upgraded to `strict` on purpose.

## Platform support

| Client | Status | Notes |
| --- | --- | --- |
| Claude Code | ✅ verified | skills + MCP + optional enforcement hook |
| opencode | ✅ verified | `~/.config/opencode/opencode.json` |
| Cursor | ⚪ spec-compatible* | copy into project; no stable plugin dir yet |
| VS Code (+Copilot) | ⚪ spec-compatible* | MCP support rolling out |
| Cline / Windsurf | ⚪ spec-compatible* | stdio server entry maps directly |

\* honest states: formats are spec-compatible and expected to work, but not yet
exercised by the maintainers. If you verify one, open a PR updating this table.

## Optional dependencies

```bash
pip install -r server/requirements.txt
```

| Extra | Upgrades | Without it |
| --- | --- | --- |
| `jsonschema` | `schema_validate` → full Draft 2020-12 | built-in subset validator |
| `pyflakes` | `verify_code` → pyflakes F821 analysis | built-in AST walk |
| `pyyaml` | SKILL.md frontmatter → full YAML | built-in lite parser |

## Configuration (`agentseed.config.json`)

| Key | Effect |
| --- | --- |
| `allowlist` | scan exclusions (replaces built-in test-idiom list) |
| `severities` | per-group severity override (`error` \| `warning` \| `info`) |
| `timeout` | default `sandbox_run` timeout, seconds (1–120) |
| `extra_tokens` | extend the hallucination word pool at runtime |
| `suppress_symbols` | names `verify_code` never flags (reported in `suppressed`) |
| `known_packages` | packages `check_imports` treats as known (stdlib + common + this list) |
| `sandbox_allowed_prefixes` | **allowlist of executables** `sandbox_run` may launch; PATH-resolved, separator-boundary enforced (absent = unrestricted) |
| `sandbox_env` | `"inherit"` \| `"scrub"` — `scrub` drops credential-looking env vars |
| `hook_profile` | guard_hook gate profile: `advisory` (default, report only) \| `diff` (block only new signals) \| `strict` |

Unknown keys are warned on stderr — a typo is never silently ignored.

> ⚠️ **Security note:** `sandbox_run` executes real processes with your user's
> permissions. Gate it behind user approval; set `sandbox_allowed_prefixes` in
> shared/CI environments. Commands resolve through `PATH` to absolute paths
> before execution, so a hostile `cwd` cannot shadow an allowlisted binary;
> unmatched commands are refused (exit -10) without running.

## Compatibility & graceful degradation

| Host capability | What you get |
| --- | --- |
| Full Agent Plugins | drop-in: skill + MCP auto-discovered, `${PLUGIN_DATA}` config honored |
| MCP-capable client | all 10 tools via registration |
| Skills-only client | skill workflow; verification degrades to `guard_cli.py` via shell |
| Plain terminal / CI | CLI gates with exit codes |

## Built-in guardrail library (EN / 中文 / 日本語)

`PROMPT-POOL` (copy-paste guardrail prompts) · `HALLUCINATION-PATTERNS`
(failure-mode catalog) · `VERIFICATION-CHECKLIST` (executable end-of-task
checklist) · `SDD-CONTRACT` (the contract every task must satisfy) ·
`DEFAULT-NORMS` (senior-engineer operating norms, mapped to the gate that
enforces each; English only) · `VENDOR-SOLUTIONS` (adoption map of vendor
techniques). Every library lives under
`skills/verify-before-code/references/`, and the SKILL files list them.

## Why AgentSeed vs. alternatives

| | Prompt-only guardrail skills | Static import linters (MCP) | **AgentSeed** |
| --- | --- | --- | --- |
| Touches code | ❌ prompt only | ✅ import graphs | ✅ AST + lexical (registry-wide) |
| Runs verification tools | ❌ | lint gates | ✅ 10 MCP tools incl. sandbox |
| Hallucination-language scan | ❌ | ❌ | ✅ stub/oversold/fabricated/fabricated_url, EN + CJK |
| Enforcement | soft (skill text) | CI gate | **tiered**: skill + MCP + CI exit codes + hook profiles (advisory → diff → strict) |
| 1.0.0 conformance linter | ❌ | ❌ | ✅ first |

## FAQ

**Does it need a specific LLM?** No — client-agnostic and model-agnostic; the
gate is enforced by skill + MCP + hooks + CI, not by any model.

**Zero dependencies?** Yes. The MCP server is pure Python standard library.

**Does the hook block my edits by default?** No. The default profile is
`advisory`: every write is scanned and the findings land in the verdict
(evidence you can act on), but nothing is interrupted. Use `diff` to block
only *new* signals, or `strict` to block every error-severity finding.

**What is an evidence receipt?** A machine-checkable completion record: the
checks you ran (tool + status), the SHA256 of every file verified, and a
digest of the receipt itself, linked from the audit log. `guard_cli receipt`
builds one; the skill's Gate 4 says a completion report cites it.

**Does it work with our existing AGENTS.md / CLAUDE.md?** Yes — it
complements them. Those files carry project facts (prose, persuasive);
AgentSeed carries the behavior contract and the hard enforcement.

**How do I extend it to another language?** Add a `LangSpec` registry entry in
`server/engine/symbols.py` — one config, no engine change. If a toolchain
verifier exists for your language, an adapter in `server/engine/verifiers.py`
buys you compiler-grade analysis for the same one-entry cost.

## Contributing

Issues, PRs and ideas welcome — or open an issue for a hallucination pattern
we haven't catalogued yet. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

PolyForm Noncommercial 1.0.0 © AgentSeed. Free for research, learning, and personal use; commercial use requires a separate license. See [LICENSE](./LICENSE).

---

<div align="center">

</div>
