# AgentSeed — Technical Design

> English technical design for AgentSeed. Also in [中文](./DESIGN.zh.md) · [日本語](./DESIGN.ja.md).

## 1. Background & problem

### 1.1 The spec is real, but oversold

Agent Plugins **1.0.0** is a genuine open specification published in August 2026.
Its Technical Steering Committee draws one representative each from **Amazon,
Cursor, Microsoft, OpenAI, and Vercel**. Two corrections to the hype:

- **Google is NOT on the committee.** "Six giants jointly launched it" is content-farm
  inflation of "vendor-neutral standards body."
- It is a **packaging standard**, not a product. It standardizes the "box"
  (`plugin.json`, `skills/`, `mcp.json`) but deliberately leaves two gaps.

### 1.2 The two spec gaps (our opportunity)

1. **No enforcement mechanism.** A client *may* load a skill; nothing forces the
   model to actually verify its output before claiming done.
2. **No registry / marketplace / distribution** — distribution is open (directories,
   VCS). And crucially, **no official 1.0.0 linter** exists despite the spec's
   MUST/SHOULD rules.

### 1.3 Market gap

| Existing | What it does | What it misses |
| --- | --- | --- |
| Chat-honesty guardrails (behavioral MCP servers) | Keep chat answers honest (don't invent citations/dates) | No code, no tooling |
| `obra/superpowers` | Prompt-only coding workflow | No hard verification |
| Static import linters (e.g. Rigour-style MCP) | Detect hallucinated imports per language gate | No behavioral scan, no skill workflow |
| Typical MCP servers | Expose an API to the model | None *verify the model's own emitted code* |

AgentSeed fills: **code-level + real tooling + Skill/MCP closed-loop enforcement.**
`check_plugin` is a first-mover 1.0.0 linter.

## 2. Design goals

- **Cross-client** — conforms to 1.0.0, loads anywhere the spec is supported.
- **Closed-loop enforcement** — soft Skill instruction bound to a hard MCP gate.
- **Zero dependencies** — pure standard-library Python; no SDK version drift.
- **First-mover linter** — `check_plugin` for 1.0.0.

## 3. Architecture

```
            ┌─────────────────────────────────────────────┐
            │  Coding agent (Cursor / VS Code / Copilot)  │
            └───────────────┬───────────────┬─────────────┘
                            │ loads          │ launches (stdio)
                            ▼                ▼
                 ┌──────────────────┐  ┌──────────────────────────┐
                 │  Skill           │  │  MCP Server (agentseed)   │
                 │  verify-before-  │  │  guard_server.py          │
                 │  code            │  │    │                      │
                 │  (gate logic)    │  │    ▼                      │
                 └────────┬─────────┘  │  guard_engine.py          │
                          │ instructs  │   ├ detect_undefined_      │
                          │ agent to   │   │   symbols (AST)        │
                          │ call:      │   ├ scan_hallucination_    │
                          │            │   │   words (regex)        │
                          │            │   └ check_plugin_          │
                          ▼            │       conformance (JSON)   │
                 ┌──────────────────┐  └──────────────────────────┘
                 │  SDD-CONTRACT     │
                 │  (loaded before  │
                 │   coding)        │
                 └──────────────────┘

  Flow: load contract → implement → verify_code + scan_hallucination →
        both pass? → mark done. Otherwise fix and re-run.
```

### 3.1 Component responsibilities

| File | Role |
| --- | --- |
| `plugin.json` | 1.0.0 manifest (`name: agentseed`) |
| `mcp.json` | declares the stdio `agentseed` MCP server |
| `skills/verify-before-code/SKILL.md` | non-skippable 4-gate guardrail |
| `references/SDD-CONTRACT.md` | contract the agent must load before coding |
| `references/DEFAULT-NORMS.md` | senior-engineer norms, each bound to its enforcing gate (EN only) |
| `references/PROMPT-POOL.md` | copy-paste guardrail prompts (EN/ZH/JA) |
| `references/HALLUCINATION-PATTERNS.md` | failure-mode catalog (EN/ZH/JA) |
| `references/VERIFICATION-CHECKLIST.md` | executable end-of-task checklist (EN/ZH/JA) |
| `references/VENDOR-SOLUTIONS.md` | vendor technique adoption map (EN/ZH/JA) |
| `server/guard_engine.py` | pure-stdlib checks behind every tool |
| `server/engine/symbols.py` | undefined-symbol detection: Python AST, TS/JS lexical, config-driven registry |
| `server/engine/verifiers.py` | toolchain verifier adapters (ruff/pyflakes/mypy/tsc/eslint/go vet/cargo/javac) behind `verify_file` |
| `server/engine/hallucination.py` | grouped word-pool scanner (EN + CJK), severity model |
| `server/engine/sandbox.py` | bounded execution channel (no shell, tree kill, env scrub) |
| `server/engine/audit.py` | JSONL verification audit trail |
| `server/engine/receipt.py` | evidence receipts: checks + file SHA256s + self digest |
| `server/engine/artifact.py` | generic plugin packer behind `plugin pack` |
| `server/guard_server.py` | hand-written JSON-RPC stdio MCP server |
| `server/guard_hook.py` | client-enforcement hook with gate profiles (advisory/diff/strict) |

## 4. MCP interface contract

Transport: line-delimited JSON-RPC 2.0 over stdio. Server name `agentseed`,
version `0.6.3`, protocol `2024-11-05`.

### 4.1 `initialize` → result
```json
{ "protocolVersion": "2024-11-05",
  "capabilities": { "tools": {} },
  "serverInfo": { "name": "agentseed", "version": "0.6.3" } }
```

### 4.2 `tools/list` → tools
- `verify_code(source: string, language?: string)` → `{language, suspects[], note}`
  — `language` defaults to `python`; the accepted set is enumerated by
  `canonical_languages()` / `SUPPORTED_LANGUAGES` and the schema `enum` is
  generated from it, so registering a language updates `tools/list` too.
- `verify_file(path: string, language?: string, engine?: string)` →
  `{ok, path, language, engine, suspects[], findings[], note}` — runs a
  project toolchain verifier when installed (engine `auto`), the built-in
  analyzer (`builtin`), or the named adapter; an explicit missing adapter
  fails loudly instead of degrading silently.
- `check_contract(source: string, contract: string, language?: string)` →
  `{language, contract_ok, missing[], prohibited_hits[], note}`
- `check_imports(source: string, language?: string, manifest?: string, manifest_kind?: string)` →
  `{language, imports_ok, suspicious[{package, line}], note}` — slopsquatting guard;
  with `manifest`, scans dependency-manifest text instead (requirements/pyproject/package.json)
- `resolve_symbol(names: string[], root?: string)` →
  `{results[{name, exists, defined_in[], stdlib_or_known_package, suggestions[]}], all_found, project_symbols, note}` —
  write-time prevention; the complement of verify_code
- `scan_hallucination(source: string)` → `{hits[{word,group,line}], clean: bool, groups{}}`
- `check_plugin(path: string)` → `{ok: bool, errors[], warnings[]}`
- `sandbox_run(command: string[], timeout?: int, cwd?: string, expected_exit?: int, expect_output?: string)` →
  `{exit_code, stdout, stderr, timed_out}`
- `schema_validate(instance: any, schema: object)` → `{valid: bool, errors[]}`
- `record_verification(task: string, checks?: [{tool, status, summary?}], summary?: string, files?: string[])` →
  `{ok: bool, path: string, total: int, error?: string}` — `status` is
  `pass` | `fail` | `skipped`

### 4.3 `tools/call` example
Request:
```json
{ "jsonrpc":"2.0", "id":3, "method":"tools/call",
  "params": { "name":"verify_code",
              "arguments": { "source":"def f():\n    return magic_unknown()\n",
                             "language":"python" } } }
```
Response (text content carries the JSON result):
```json
{ "content": [ { "type":"text",
  "text": "{\"language\": \"python\", \"suspects\": [\"magic_unknown\"], \"note\": \"...\"}" } ] }
```

## 5. Key algorithms

### 5.1 `detect_undefined_symbols`
Backend passes:
- **Python (AST):** parse with `ast`, collect defined names (builtins, imports
  asnames, def/class names, args), then walk for `Name`/`Call` loads not in the
  defined set.
- **TypeScript/JavaScript (lexical):** regex pass collecting imports (named/
  default/namespace/destructured), declarations (function/class/interface/type/
  enum/const/let/var), function params, then flags top-level calls and `new`
  expressions whose callee is never defined (member access `obj.foo()` is not
  flagged; keywords/globals are whitelisted).
- **Generic registry (lexical):** one engine, many languages. Each `LangSpec`
  (go/rust/java/c/c++/c#/php/ruby/kotlin/swift/dart/lua/r/zig) declares comment/string syntax,
  keywords, globals, definition/import/param regexes, and a parameter-name
  mode. The shared engine masks comments/strings, collects definitions, then
  flags bare calls and `new` whose callee is undefined. Adding a language is a
  registry entry, not an engine change; Ruby's paren-less calls are supported
  via the `bare_calls` flag.
**Scope/limits:** static only, no runtime; the TS and generic passes are
lexical, not type checkers — attribute calls (`obj.m()`, `a::b()`), macros,
and cross-file symbols are not analyzed; dynamic/global references may
produce false positives, destructured edge cases may be missed.

### 5.2 `scan_hallucination_words`
Word-boundary regex scan over a **grouped pool of 50+ signals**:
- `stub_code`: stub/mock/fake/placeholder/dummy/todo/fixme/xxx/tbd/tba/wip/
  "not implemented"/"coming soon"
- `oversold`: guaranteed/"definitely works"/"all tests pass"/"everything works"/
  "fully tested"/"production ready"/"no bugs"/"works perfectly"/"should work"/
  "trust me"/"works on my machine"/"100% correct"/"bug free"/"zero errors",
  plus unverified security claims ("no vulnerabilities"/"secure by design"/
  "unhackable") and performance claims ("highly optimized"/"zero downtime")
- `fabricated`: simulated/hypothetical/imaginary/invented/fabricated/fictional/
  pretend/"made up"
- `fabricated_url`: structural domain pass — placeholder stand-ins
  ("api.yourdomain.com"), reserved TLDs used as if real ("myapp.test"), and
  "example" fabricated into non-reserved domains ("docs.example-fake-api.dev");
  the reserved example.com/net/org/edu set stays clean
Returns `hits[]` (word/group/line), `clean`, and per-group counts.
Source: SFD Lab 5-step anti-hallucination checklist (step 5); CDV
("'done, all tests pass' is a claim, not evidence"); reze83
verify-before-claim rules.

### 5.3 `check_plugin_conformance`
Validates `plugin.json` (`$schema` = 1.0.0 address, required `name`, valid JSON),
each `skills/*/SKILL.md` presence, and `mcp.json` (`$schema`, `mcpServers`).
Returns `ok`, `errors[]`, `warnings[]`.

## 6. 1.0.0 conformance checklist

| Spec section | Requirement | AgentSeed |
| --- | --- | --- |
| §5.2 manifest | root `plugin.json`, closed schema (only `$schema`/`name`/`version`/`description`/`author`/`homepage`/`repository`/`license`/`keywords`/`extensions`) | ✅ |
| §5.3 required | `$schema` = 1.0.0 address; `name` required | ✅ |
| §5.5 name | 1–64 chars, `[a-z0-9.-]`, alphanumeric ends, no `--`/`..` | ✅ |
| §5.4 metadata | `repository`/`homepage`/`license` are strings; `author` limited to `name`/`email`/`url` | ✅ |
| §6.1/§7.1 skills | `skills/<name>/SKILL.md`; Agent Skills frontmatter (name matches dir, description ≤1024) | ✅ |
| §7.2 mcp.json | only `$schema` + `mcpServers`; stdio server with `command`, `cwd` = `${PLUGIN_ROOT}` | ✅ |
| §8 discovery | client reads manifest + skills + mcp | ✅ (by design) |
| §11 linter | (spec ships none) | ✅ `check_plugin` strict 1.0.0 linter |

## 7. Competitive comparison

| | Prompt-only skills (superpowers…) | Static import linters | **AgentSeed** |
| --- | --- | --- | --- |
| Touches code | ❌ | ✅ import graphs | ✅ AST + lexical |
| Runs tools | ❌ | lint gates | ✅ 10 MCP tools incl. sandbox |
| Enforcement | soft | CI gate | **hard gate** |
| 1.0.0 linter | ❌ | ❌ | ✅ |

## 8. Risks & explicit non-goals

Risks:

- Static scope analysis → false negatives on dynamic/attribute access.
- Spec is young (Aug 2026); client adoption and schema may shift.
- Enforcement depends on the client honoring the skill's gate instruction;
  the hard layer is `guard_cli gate` in CI.

Explicit non-goals (stated so nobody mistakes them for bugs):

- **Semantic correctness**: code that runs but is logically wrong is out of
  scope — no runtime oracle exists at plugin level.
- **Attribute-call verification** (`obj.missing_method()`): requires type
  inference across files; documented false-negative class.
- **Cross-file symbol resolution**: analysis is single-file by design
  (zero-dependency, O(source)).
- **Full sandbox isolation**: `sandbox_run` is a deterministic execution
  channel with tree-kill and optional env scrubbing, not a container.

## 9. Build & test

```bash
python3 server/guard_engine.py                 # self-check + demos
# MCP handshake + a tools/call:
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' \
            '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 server/guard_server.py
```

## 10. Adapters, gate profiles, receipts, and the plugin toolchain

### 10.1 Verifier adapters (`engine/verifiers.py`)

The registry proves "cheap and broad"; the adapters prove "deep where it
matters". A `VerifierSpec` (name, languages, binary, fixed args, parser id)
runs the project's own toolchain through `sandbox_run` — no shell, capped
output, timeout, tree kill — and extracts only the undefined-name class
(F821 / name-defined / TS2304 / `undefined:` / E0425 / no-undef / `cannot find symbol`) into the same `suspects`
shape the built-in analyzer returns. Policy:

- `auto` = first installed adapter, else the built-in analyzer (noted);
  an explicit adapter name that is missing or fails to run is a loud error,
  never a silent degrade — a broken adapter parsed as "clean" would be the
  exact false-green this project exists to prevent.
- Adapters are PATH-resolved absolute binaries; `sandbox_allowed_prefixes`
  intentionally does not gate them (running AgentSeed already implies
  running the project's declared toolchain).
- Adding an adapter is one `VerifierSpec` entry plus one parser function.

### 10.2 Hook gate profiles (`guard_hook.py`)

A lexical scanner's false positives must never be able to block legitimate
work — a gate that cries wolf is disabled, and a disabled gate enforces
nothing. The hook therefore profiles its own power:

| Profile | Blocks | Rationale |
| --- | --- | --- |
| `advisory` (default) | never | evidence and visibility; zero interruption |
| `diff` | only new `group\|word` counts or new suspect names vs the file's previous on-disk content | hook-level analogue of `scan --baseline` |
| `strict` | any error-severity hit or suspect | pre-0.4 behavior, opt-in |

The verdict's `blocking` field is the profile's decision, not the raw scan;
`status` is `pass` / `flagged` / `blocked` / `skipped`.

### 10.3 Verification coverage (`engine/audit.py`)

A receipt freezes what you CLAIM to have verified; coverage names what you
changed but never verified — the self-awareness hallucination class. The
gate's coverage stage diffs `git status --porcelain` against the files
recorded via `record_verification(files=...)` and lists the gap. It reports
by default and blocks only under `--coverage-strict`; outside a git worktree
it degrades to an honest "cannot compute", never a fake pass.

### 10.4 Evidence receipts (`engine/receipt.py`)

A receipt freezes the verification state of a completed task: checks
(tool + status), SHA256 + size of every verified file, agentseed/python/
platform versions, and the digest of the receipt file itself — re-hash it
to detect any later edit. One JSONL audit line links to it. A named file
that does not exist fails the whole receipt loudly. This is the artifact a
completion report cites instead of prose.

### 10.5 Plugin toolchain (`guard_cli plugin …`)

`init` scaffolds a minimal plugin and then lints it with the real
conformance checker, deleting the tree if it cannot pass (a scaffold that
fails its own linter must not be left behind); `validate` re-runs the
linter; `pack` builds a deterministic zip (skip rules shared with the
release packer via `engine/artifact.py`, fallback constants pinned by a
drift test); `doctor` reports interpreter, optional deps, adapter presence,
config warnings, a live MCP handshake (tools/list count), and conformance.

## 11. Project symbol index (`engine/index.py`)

Single-file scope analysis is honest but blind to the project. The index
gives the built-in analyzer a cross-file judgment without a type checker:

- Collection reuses the exact per-language collectors behind
  `defined_symbols` — no second parser to drift.
- Entries are cached per file under `<root>/.agentseed/index.json`, keyed by
  content hash; unchanged files are never re-scanned, so a gate costs
  seconds on large repos.
- Differential judgment: a raw suspect that exists in the index is
  reclassified as `missing_imports` (defined elsewhere, not imported here —
  a real bug with a different fix, listing the defining files); a suspect
  absent from the index stays a suspect with did-you-mean suggestions drawn
  from the whole project's symbol pool.
- Both verdicts still gate; `verify_file` (builtin path), `guard_cli
  verify`, and the `gate` symbols stage all consult it; config
  `project_index: false` turns it off, and outside a detectable project
  root the behavior is exactly the 0.3.x single-file analysis.
