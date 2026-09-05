# Changelog

All notable changes to AgentSeed are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com); versioning follows [SemVer](https://semver.org).

## [0.6.2] — 2026-09-06

### Changed
- **npm package README now carries the full install instructions** - the
  npm install route (`npm install -g agentseed-mcp` / `npx
  agentseed-mcp`) joins the release-download and clone routes in all
  three quick starts, so the npmjs.com package page teaches every route.
- Local gate artifacts (`baseline-scan.json`, `.mimosa/`) are gitignored.

No engine changes; 0.6.1 functionality is identical.

## [0.6.1] — 2026-09-06

### Added
- **Trilingual skill parity guard** (`server/test_skill_parity.py`): every
  shipped MCP tool must be named in all three SKILL languages, gate structure
  counts must agree, and the v0.6.0 capability tokens (expected_exit,
  expect_output, manifest, record_verification) must be present everywhere.
  This is the guard that would have caught the ja skill's missing
  execution-evidence paragraph and the zero-mention tools before release.

### Fixed
- README.zh.md: removed a duplicated honesty-boundary line.
- Installed-copy `mcp.json` command pinned to the real interpreter on
  Windows (the shipped spec default `python3` does not exist there).

## [0.6.0] — 2026-09-05

Hardening release: every addition closes a gap named in the 2025
hallucination literature (CodeHalu's executional verification, the
slopsquatting first-contact surface, the agent-hallucination surveys'
self-awareness class) while keeping the zero-required-dependency
contract and the self-conformance gate green.

### Added
- **`resolve_symbol` — the 10th MCP tool (write-time prevention).**
  verify_code judges code after it is written; `resolve_symbol` answers
  "does this name exist?" BEFORE the call is written, against the project
  symbol index plus stdlib/known packages, with did-you-mean suggestions
  from real symbols.
- **`fabricated_url` scan group (phantom squatting).** A structural
  domain pass joins the three literal-token groups: placeholder stand-ins
  (`api.yourdomain.com`), reserved TLDs used as if real (`myapp.test`),
  and "example" fabricated into non-reserved domains. The RFC/IANA
  example.com/net/org/edu set stays clean; default severity warning.
- **Dependency-manifest scanning (`check_manifest`).** The slopsquatting
  first-contact surface: `guard_cli imports --manifest` and the
  `check_imports` tool's `manifest`/`manifest_kind` args scan
  requirements*.txt, PEP 621 pyproject arrays, Poetry dependency sections
  and package.json dependency objects (npm has its own curated known set).
- **`sandbox_run` behavioral assertions.** Optional `expected_exit` and
  `expect_output` upgrade "the command ran" to "it ran as expected"
  (CodeHalu's executional verification, minimally); the result gains an
  `expectations` verdict, and CLI `sandbox --expect-exit/--expect-output`
  exits on the assertion verdict.
- **Gate verification-coverage stage.** `record_verification` persists
  `files`; the gate's coverage stage diffs `git status --porcelain`
  against them and names changed-but-unverified files. Report-only by
  default; `--coverage-strict` blocks; non-git roots degrade to an honest
  "cannot compute". AgentSeed's own state never counts as work.
- **`baseline audit` subcommand.** The review loop for the frozen scan
  baseline: composition by group, loudest frozen signals, and the
  prune-allow-freeze discipline. Report-only.
- **mypy and javac toolchain adapters.** mypy joins the Python auto-chain
  (`name-defined`); javac covers Java from its stderr stream
  (`cannot find symbol` + symbol line).

### Changed
- **Oversold pool: unverified security and performance claims.**
  "no vulnerabilities", "secure by design", "unhackable", "highly
  optimized", "zero downtime" (and ZH counterparts) are the same
  evidence-free class as "production ready"; legitimate hardening and
  optimization descriptions stay clean (negative-tested).
- **`--strict` severity promotion is registry-driven** — every
  default-warning group (now stub_code and fabricated_url) blocks,
  instead of a hardcoded stub_code entry.
- **Non-zero adapter exits with zero extracted findings must show at
  least one diagnostic-shaped line** — a tool that failed to run is never
  parsed as clean; "ran but reported only other diagnostic classes" stays
  an honest class-scoped pass.
- **Tool count 9 → 10 and group count 3 → 4** across all three languages'
  README/DESIGN/SKILL, with the adapter list and the ja README's stale
  "8 tools" heading corrected along the way.

### Fixed — field-tested against five real-world repositories
  (flask, requests, django 2930-file gate, gin, axios) — every class below
  was a false positive found in real code, then regression-tested:

- **Single-quote string patterns are line-bounded** in the 11 languages
  where single quotes never span lines (go/rust/java/c/cpp/csharp/kotlin/
  dart/lua/r/zig). An apostrophe in a comment ("doesn't") opened a
  multi-line bogus string span that swallowed following code — gin's
  same-file `processAccounts` definition became a suspect.
- **The TS/JS native pass masks strings and comments** before scanning
  (JSDoc text "EF BB BF (the UTF-8 BOM)" matched the bare-call pattern and
  flagged `BF` on axios), collects **object destructuring from any
  initializer** (`const {getPrototypeOf} = Object`), **class/object method
  definitions and their parameters** (`constructor(x) {` is a definition,
  not a call; `forEach(fn) { fn(h) }` defines fn), **arrow params without a
  declaration prefix** (`lookup = (host, opt, cb) =>`), and **common
  Web/Node globals** (URL, Uint8Array, TypeError, XMLHttpRequest,
  ReadableStream, ...). Member chains split across lines (prettier style
  `foo.
  replace(...)`) are no longer misread as bare calls.
  Result: axios/lib 62 real JS files — 9 files with suspects before, 0 after.
- **The symbol-index cache records the engine version** and rebuilds when
  it differs — a cache written by older collection rules otherwise keeps
  serving stale judgments after an engine fix.
- **Manifest scanning diff-scopes against git HEAD** (`imports --manifest`):
  a long-tail unknown the project already depends on is reported separately
  as `preexisting_unknown`; only NEWLY ADDED names are suspects. Without
  this the report flagged 49 of axios's 62 real dependencies — noise that
  trains users to ignore the report. On a real axios clone: 0 suspects.
- **Python detection honors `# noqa` lines** (flake8 convention — django's
  own tests mark forward-reference annotations `# NOQA: F821`) and skips
  dunder protocol names (`__path__`, `__version__`). django gate suspects
  across 2930 files: 5 → 0; the only remaining finding is django's own
  deliberately-broken syntax fixture.
- **Coverage excludes `__pycache__/`** — interpreter cache is not work.

## [0.5.0] — 2026-08-30

### Changed
- **License: Apache-2.0 → PolyForm Noncommercial 1.0.0.** Research,
  learning, personal, and educational use remain free; selling the
  software, selling services built on it, or bundling it into paid
  products now requires a separate commercial license from the
  maintainers. All manifests (`package.json` / `plugin.json` /
  `server.json`), skill frontmatter, badges, and `LICENSE` updated —
  the `examples/plugins/broken-plugin` fixture intentionally keeps its
  old header. Sister project ScholarSeed switched to the same license
  on the same day, keeping the anti-hallucination matrix consistent.

## [0.4.1] — 2026-08-28

### Changed
- **npm listing polish (packaging-only release).** Added `keywords` (14
  search terms), `author`, and a description that states what 0.4.0
  actually ships, so the package page and npm search present the project
  accurately. Code is identical to 0.4.0 apart from manifest metadata.

## [0.4.0] — 2026-08-28

### Added
- **`verify_file` (ninth MCP tool) and toolchain verifier adapters.** The
  built-in lexical passes are honest but shallow; `verify_file` runs the
  project's own tools — ruff/pyflakes (Python), tsc (TypeScript), eslint
  (JavaScript), go vet (Go), cargo check (Rust) — through the same bounded
  execution channel and reports only the undefined-name class in the same
  `suspects` shape. `engine=auto` picks the first installed adapter and
  falls back to the built-in analyzer with a note; an explicit engine that
  is missing or fails to run is a loud error, never a silent degrade.
- **Hook gate profiles.** `guard_hook.py` now has three profiles (config
  `hook_profile` or `--profile`): `advisory` reports findings and never
  blocks (default), `diff` blocks only signals NEW relative to the file's
  previous content, `strict` is the old blocking behavior. The verdict's
  `blocking` field is the profile's decision, and `status` gains `flagged`.
- **Evidence receipts.** `guard_cli receipt <task> --check TOOL=STATUS
  --file PATH` builds a self-verifying completion record: checks, SHA256 of
  every verified file, and the digest of the receipt itself, linked from
  the JSONL audit log. A named file that does not exist fails the receipt
  loudly.
- **Plugin toolchain.** `guard_cli plugin init|validate|pack|doctor`:
  scaffolding that must pass its own conformance linter or be deleted, a
  deterministic `plugin pack` zip sharing the release packer's skip rules
  (fallback constants pinned by a drift test), and a `doctor` environment
  report including a live MCP handshake.
- **`guard_cli gate` now works on any repo.** Without a `plugin.json` the
  conformance stage skips (enforce it with `--require-conformance`), and a
  missing baseline is created on the first run instead of failing.

- **Cross-file project symbol index.** The built-in analyzer no longer
  judges a file blind: a project symbol index (cached under
  `.agentseed/`, keyed by content hash, rebuilt incrementally) lets it
  split raw suspects into two verdicts — `suspects` (defined nowhere in
  the project: high-confidence hallucination) and `missing_imports`
  (defined elsewhere but not imported here: a real bug with a different
  fix, listed with the defining files). Both still gate. Disable with
  config `project_index: false`.
- **`guard_cli init` — one command from clone to working gate.** Writes a
  starter `agentseed.config.json`, generates `.github/workflows/agentseed.yml`
  (clones the plugin in CI and runs the gate), runs the first gate to
  bootstrap the baseline, and prints the exact MCP snippet (`command` +
  `args` with absolute paths) to point any client at the plugin you cloned,
  plus the Claude Code CLI one-liner.
- **One-key noise decay: `guard_cli suppress NAME` / `guard_cli allow
  WORD`.** Suppress stops `verify_code` flagging a project symbol (still
  reported in `suppressed`); allow writes `extra_allowlist`, which merges
  AFTER the built-in test-idiom defaults, so allowing one word never drops
  the defaults the way replacing `allowlist` would. Both edit the
  project's `agentseed.config.json` atomically and refuse to clobber a
  config that fails to parse.
- **Did-you-mean suggestions.** Undefined-symbol findings now carry the
  closest real names (in-file or project-wide), turning a flagged symbol
  into a seconds-long fix.
### Fixed
- TypeScript/JavaScript array destructuring was not collected, so every
  React hook setter (`setCount`) was flagged as a hallucinated symbol.
- Ruby local-variable assignments (`sum += i`, `x ||= y`) and block
  parameters (`each { |i| ... }`) were not collected, so under `bare_calls`
  every ordinary local read was a false suspect.
- A Python wildcard import (`from x import *`) now honestly disables
  undefined-name detection for that module instead of flagging most real
  code as hallucinated.

- **A one-shot pipe client no longer loses the final response.** The
  documented `printf ... | guard_server.py` pattern closes stdin right
  after the last request; the read loop exited at EOF while worker
  threads (daemons) were still running, killing the final tools/call
  reply. main() now drains pending requests for a bounded window before
  exiting.
- **npm publishing is operator-switchable.** The release workflow's npm steps
  honor the repository variable `NPM_PUBLISH_ENABLED` (default enabled;
  `false` is an explicit operator decision reported loudly in the run summary
  — never a silent skip; with the variable enabled, a missing `NPM_TOKEN`
  still fails the run as before). GitHub Releases remain the single source
  of truth for the zip artifact, and the release workflow mirrors that
  artifact to the npm registry in one run.
### Changed
- **The hook defaults to `advisory`.** The pre-0.4 default blocked every
  write with an error-severity word hit or any undefined-symbol suspect —
  measured on real code (React components, ordinary comments) that meant
  blocking legitimate work. Blocking still exists: `diff` for growth-only,
  `strict` for maintainers who tuned their config. Tests pin the new
  contract.

## [0.3.2] — 2026-08-28

Everything below is the delta against the *published* 0.3.1 artifact, not
against its tag message.

### Fixed
- **The published artifact no longer carries maintainer-local state.**
  `server/.agentseed/verification-log.jsonl` was being packed into the release
  zip, leaking absolute paths from the machine that built it. The packer's skip
  rules are now module constants and its documentation set is explicit, so the
  exclusions are auditable instead of emergent. This changes the contents of
  what you download, which is why this is a release rather than a CI-only tweak.
- **The release path can be replayed.** Re-running `release.yml` against an
  existing tag used to fail on the GitHub Release step and on `npm publish`
  with `E403 cannot publish over the previously published version`. Both are now
  idempotent: an existing release is updated in place, and an existing npm
  version is compared by `dist.shasum` against a local `npm pack` — identical
  bytes exit green, differing bytes fail loudly rather than silently diverging.
- **A release that cannot publish is now a failed release.** `release.yml` had
  gated its npm step on `NPM_TOKEN` being set, so a repository with no token
  produced a green run that published nothing — the same class of false green as
  a scanner reporting `clean` for a file it never opened. The workflow now
  asserts the credential exists and fails with an actionable message otherwise.
- **The npm artifact is hygiene-gated, not only the zip.** `npm pack`
  whitelists whole directories (`bin/`, `server/`, `skills/`) and never runs
  the packer, so a nested `.npmignore` per whitelisted directory is what keeps
  maintainer-local state (verification logs, caches, garbage logs) out of what
  users install. Their rules are pinned to `scripts/pack.py` by a drift test,
  and the release workflow now fails if the tarball would ship any of it.
- **`server/requirements.txt` is installable on the oldest interpreter we
  support.** The optional-dependency pins had drifted above the Python 3.9
  floor that the CI matrix and the bare-env job both claim to test, so a
  documented install could not complete. Dependabot is now told to stop opening
  bumps past that ceiling, which is what had been turning the queue red.

### Changed
- CI discovers test files instead of carrying a hard-coded list, installs from
  `server/requirements.txt`, pins the linter, and verifies the exact artifact it
  is about to publish before publishing it.

### Infrastructure
- The repository history was consolidated onto a single identity across all
  three forges and rebuilt as one commit per meaningful change; the released
  `v0.2.0` commit had never been tagged, so `v0.2.0` is added here and every
  release tag is now annotated. File contents are unchanged by the
  consolidation — each rebuilt commit reproduces the tree of an existing one.

## [0.3.1] — 2026-08-27

A full audit of the 0.3.0 release. Everything below was reproduced against the
published tag before being fixed; several items were self-inflicted failures of
the exact discipline this plugin sells.

### Security
- **`guard_cli` no longer reports a false green for a missing path.**
  `_read_source()` treated any unreadable argument as inline source text, so
  `scan src/ --strict` (the command in our own README) on a typo'd or absent
  path returned `clean: true` / exit 0, and `imports` returned
  `imports_ok: true`. An argument that looks like a path but does not exist is
  now a usage error (exit 2); `scan --baseline` on a missing target fails the
  same way instead of raising an uncaught `FileNotFoundError`. A guardrail that
  reports "clean" for code it never read is the failure mode this project
  exists to prevent.
- **Hook registration never destroys a client config.** `guard_hook register`
  rewrote `~/.claude/settings.json` / `~/.cursor/hooks.json` with
  `open(path, "w")`, truncating the user's file before writing. Writes are now
  temp-file + `os.replace` (atomic) and the previous contents are kept as
  `.bak` so a bad merge is reversible.
- **The opencode plugin resolves a working interpreter instead of assuming
  `python`.** A missing interpreter was caught by the fail-open path, so the
  gate silently did nothing. It now probes `python`/`py`/`python3` per
  platform, and every bypass path (engine not found, no interpreter, spawn
  failure) announces itself once on stderr.
- **Installers verify before extracting** (`install.ps1` extracted the archive
  and only then checked `-Sha256`; `install.sh` had always done it in the right
  order) and **never overwrite a previous install in place** — the old copy is
  moved aside to `<dir>.bak-<timestamp>`.
- `SECURITY.md` no longer lists buffered child output as a known limit; 0.3.0
  moved to streamed tail ring buffers and the claim contradicted the code.

### Fixed
- **The documented install path installed an old release.** Both installers
  resolved the release list at the default forge, which returned entries
  oldest-first: `bash install.sh` / `.\install.ps1`
  delivered **v0.1.1** (6 tools, 13 languages) while the README described 8
  tools. GitHub is now the default forge with `/releases/latest`, so the
  newest version tag drives the download.
- **`-Repo` was silently discarded** in `install.ps1`: PowerShell variables are
  case-insensitive, so `$repo = "…"` shadowed the `-Repo` parameter.
- **`mcp.json` on Windows.** The Agent Plugins schema allows exactly one
  literal interpreter token in `command`, which shipped as `python3` — the
  Microsoft Store stub on most Windows installs. `install.ps1` now rewrites it
  to `python` in the installed copy (BOM-free, manifest kept valid), and the
  README's Windows note shows the correct shape (`command` is a string; the
  array belongs to `args`) instead of telling users to write invalid JSON.
- **The release artifact carried no documentation.** `pack.py` staged the npm
  `files` allowlist verbatim, so the zip installed to `~/.agentseed/AgentSeed`
  contained no README/SECURITY/CONTRIBUTING. The zip now also stages them.
- **v0.3.0's own tag failed lint** (`ruff` E402 on `dataclasses`) and the
  published artifact did not contain the languages its CHANGELOG/README
  advertised. Both are corrected here and the release pipeline can no longer
  repeat it (below).

### Added
- **A docs-vs-engine consistency gate** (`server/test_docs_sync.py`): language
  and tool counts in every README/DESIGN, repository references and forge
  identity, reverse-DNS registry name, `server.json` installable packages,
  version strings, and the `references/` library listing in all three SKILL and
  README files are now asserted against the registry and `tools/list`. The
  three language counts and two tool counts that shipped in 0.3.0 fail this
  test on purpose.
- **`guard_cli verify`/`contract` infer the language from the file suffix**
  (`verify src/app.go` really analyzes Go); `--language` still overrides, and
  inline text defaults to Python.
- **CI/Release**: an npm job (`node --check` + `npm pack` + global install +
  `scripts/smoke_npm.mjs`, which drives the published shim over JSON-RPC and
  asserts 8 tools and an invented-symbol finding), a `verify` job gating
  `release.yml` (tests + pinned lint + `gate` + manifest check + npm smoke),
  npm provenance via `id-token: write`, an idempotent `gh release` step,
  Dependabot for actions/npm/pip, and `ruff` pinned to a concrete version.
  CI installs engine extras from `server/requirements.txt` and discovers tests
  instead of listing files, so a new test file or dependency cannot be skipped.

### Changed
- **The language registry is now the single source of truth for file
  suffixes.** Each `LangSpec` declares its own `extensions`, the
  natively-analyzed languages live in a `_NATIVE_LANGS` table instead of
  `if language in (…)` branches duplicated across functions, and
  `canonical_languages()` / `source_extensions()` / `language_for_file()`
  derive the CLI's path heuristic, tree-scan filter, MCP schema `enum`, and the
  prompt-pool exporter's glob line. Adding a language is one table entry that
  carries its syntax, suffixes and surface with it; an entry without suffixes
  fails at import rather than becoming invisible to `gate`.
- **Repository and package identity unified as `agentseed-mcp`** across GitHub
  (`Morningstar202604/agentseed-mcp`),
  `plugin.json`/`package.json`/`server.json` URLs, the registry reverse-DNS name
  (`io.github.morningstar202604/agentseed-mcp`), installers and
  README/CONTRIBUTING — the npm package name we actually own, since plain
  `agentseed` is taken by an unrelated publisher. The installed plugin home
  (`~/.agentseed/AgentSeed`) is deliberately unchanged: it is the discovery
  convention shared by the installers and the opencode plugin, and moving it
  would only orphan existing installs.
- **Release discipline**: an unreleased change gets its own version section;
  entries may no longer be appended to a version that has already been tagged.
- `record_verification`'s documented signature in `DESIGN.md` matches the
  implementation, `DESIGN.ja.md` lists all 8 tools, and stale docstrings in
  `guard_server.py` / `guard_cli.py` enumerate the real 8-tool surface.

## [0.3.0] — 2026-08-27

### Added
- **`verify_code` — config-driven multi-language engine**: a generic lexical
  verifier backed by a language registry (`LangSpec`). Newly supported:
  Go, Rust, Java, C, C++, C#, PHP, Ruby, Kotlin, Swift
  — on top of Python
  (AST) and TypeScript/JavaScript (lexical). The same engine runs every
  registered language (mask comments/strings → collect definitions/imports →
  flag undefined bare calls and `new`); adding a language is a registry entry,
  not an engine change. Ruby's paren-less calls are supported via `bare_calls`.
  MCP `verify_code.language` and CLI `verify --language` accept all aliases;
  unsupported languages now list the supported set in `note`.
  *(Correction, 2026-08-27: Dart, Lua, R and Zig were merged after the
  `v0.3.0` tag and are therefore not in the published 0.3.0 zip or npm build —
  they ship with 0.3.1 below.)*
- **`check_contract` — verify code against a written spec**: new MCP tool +
  `guard_cli contract` subcommand. Contract is JSON
  (`{"requires": [...], "prohibits": [...]}`); `requires` names must be
  defined/imported by the source (via new public `defined_symbols`),
  `prohibits` tokens must not appear. Exits 1 on violations.
- **`scripts/export_prompt_pool.py` — wire the prompt pool into per-client
  configs**: parses `PROMPT-POOL.md` (the live pool, parsed at runtime) and renders identical
  anti-hallucination prompts as `CLAUDE.md`, `AGENTS.md`, and Cursor
  rules (`.cursor/rules/agentseed-guardrails.mdc`) so the gates apply outside
  plugin-aware clients.
- **`check_imports` — package-hallucination (slopsquatting) guard**: new MCP
  tool + `guard_cli imports` subcommand, motivated by "We Have a Package for
  You!" (USENIX Security 2025, arXiv:2406.10279 — LLMs invent non-existent
  package names in 5.2–21.7% of generated code, ~58% recur, attackers
  pre-register them). Flags top-level imports that are neither Python stdlib
  nor in the known-package set (stdlib via `sys.stdlib_module_names` +
  curated common third-party list + config `known_packages`). Python only;
  report, not a hard gate.
- **Hallucination pool expansion (research-driven)**: +15 English and
  +10 CJK low-false-positive tokens across stub/oversold/fabricated groups
  (e.g. `foolproof`, `bulletproof`, `cannot fail`, `fictitious`,
  `nonexistent`, `凭空捏造`, `子虚乌有`); guardrail library supplemented with
  2025 code-hallucination taxonomy (arXiv:2504.20799), scaffolding
  hallucination / phantom symbols (arXiv:2604.20202), and the
  false-confidence finding (Perry et al., CCS 2023).
- **README: multi-language live-tested demo** — 11 languages each catch
  their invented call; clean code zero false positives.

### Changed
- **`sandbox_run` — streamed, bounded-memory output truncation**: output was
  previously captured in full via `communicate()` then truncated, so a child
  flooding output could balloon server memory. Two daemon reader threads now
  drain stdout/stderr incrementally into tail ring buffers (8 KB / 4 KB caps),
  so memory stays bounded while the last-output tail semantics are preserved.
- `tools/list` now exposes 8 tools (was 6).

## [0.2.0] — 2026-08-26

### Security
- **`sandbox_allowed_prefixes` bypass fixed (High)**: the old matcher compared
  basenames and raw path prefixes, so on Windows a hostile `cwd` could plant
  `python.exe` to impersonate an allowlisted basename, and prefix `C:\tools\safe`
  matched `C:\tools\safe-evil\app.exe` (no separator boundary). Commands now
  resolve through `PATH`/`abspath` BEFORE execution; bare-name entries match the
  resolved basename (with `.exe` tolerance), path entries require a separator
  boundary, unmatched/unresolvable commands are refused with exit -10 without
  spawning, and allowed commands execute under their resolved absolute path.
  Regression tests cover boundary matching, `.exe` tolerance and cwd-shadowing.

### Changed
- **All `tools/call` requests now run in a worker thread** (previously only
  `sandbox_run`): a slow `verify_code`/`check_plugin` can no longer stall the
  stdio read loop. Cancellation semantics extend to every tool; responses stay
  single-writer serialized.
- **Engine public API cleanup**: config helpers renamed to public names
  (`config_str_list`, `config_severities`, `parse_timeout`,
  `config_extra_tokens`); private internals (`_decode`, `_run_command`,
  `_prefix_allowed`, `_GROUP_LABELS`, `_config_*`) are no longer re-exported
  from the `engine` package.
- **server.json honesty**: the npm registry package entry was removed until
  `agentseed-mcp` is actually published (the manifest previously advertised a
  package that does not exist in the registry). The manifest-drift test now
  accepts zero listed packages while enforcing version agreement for any that
  appear.
- **Comparison table rewritten**: the "Anti-Hallucinate (mcpmarket)" competitor
  could not be verified to exist; tables across READMEs/DESIGNs now compare
  against verifiable categories (prompt-only guardrail skills such as
  superpowers; static import linters).

### Added
- **Client-enforcement hook** (`server/guard_hook.py`, installers `--hooks` /
  `-Hooks`): registers as a Claude Code PreToolUse/PostToolUse hook so every
  `Write`/`Edit`/`MultiEdit` is scanned at the client boundary — PreToolUse
  checks the incoming `content`/`new_string` before anything lands on disk,
  and error-severity findings return as exit code 2 with the reason on stderr
  (the channel Claude Code feeds back to the model). Registration merges into
  `~/.claude/settings.json` idempotently (stale agentseed entries replaced,
  unrelated hooks preserved). Fail-open policy: infrastructure errors never
  block edits; only positive scan findings do. Honored config keys:
  `allowlist`, `severities`, `suppress_symbols`, `extra_tokens`. Covered by
  17 subprocess tests wired into both CI test jobs.
- **pyflakes enhancement is real**: `verify_code` now merges pyflakes F821
  undefined-name findings into its AST walk when pyflakes is installed (catches
  e.g. Del-context names the hand-rolled walk misses); previously the import
  existed but was never called. Zero-dep behavior unchanged when absent.
- **Baseline scan mode** (`guard_cli scan <path> --baseline F [--update-baseline]`):
  freezes a line-number-free fingerprint of known self-referential hits and
  fails only on NEW signals — the repo now ships its own `baseline-scan.json`
  (538 documented hits in tool descriptions/fixtures).
- **Composite hard gate** (`guard_cli gate --root .`): conformance linter +
  undefined-symbol sweep over all Python sources + baseline scan, one exit
  code; wired into CI as the `gate` job (ubuntu/windows). This is the hard
  enforcement layer behind the soft skill.
- **Detection benchmark** (`scripts/bench_detection.py` + `docs/BENCHMARK.md`):
  seeded synthetic corpus across five defect classes; current figures
  precision=1.0 recall=1.0 (tp=100 fp=0 fn=0). Locked by a regression test.
- **Sandbox tree-kill + env scrubbing**: timeouts and cancellations now
  terminate the whole process tree (POSIX process group / Windows
  `taskkill /F /T`); new config `sandbox_env: "scrub"` drops credential-like
  environment variables before spawn (opt-in best-effort denylist).
- **Input bounds**: MCP frames larger than 2 MB are rejected with -32600;
  JSON-Schema patterns longer than 256 chars are refused by both validator
  paths (defensive ReDoS bound).

### Fixed
- Documentation truth sweep: CHANGELOG 0.1.1 claim scoped to the English README
  only (zh/ja sync tracked below); CONTRIBUTING test count corrected;
  `README.md` platform-table dead link replaced with a concrete pointer.

## [0.1.1] — 2026-08-25

### Fixed
- **Documentation drift**: READMEs (en/zh/ja) and DESIGN.zh now state **six** MCP tools — the previously-undocumented `record_verification` audit tool was shipped but never counted. `guard_engine.py` is no longer described as running "conformance + demos"; it now actually runs a dependency-free self-check (`python server/guard_engine.py`) exercising `verify_code` + `scan_hallucination`.
- **Test hygiene**: eliminated `ResourceWarning` leaks in `test_server.py` / `test_features.py` — the MCP-server subprocess and its stdio pipes are now reaped and closed in teardown, so the suite runs clean even under `-W error::ResourceWarning`.

### Added
- **P0 infrastructure**: GitHub Actions CI (3 OS × Python 3.9–3.13 matrix with coverage, bare-env stdlib-only degradation job, ruff lint job, manifest-drift gate) and tag-triggered Release workflow (pack.py build → gh release upload → conditional npm publish). Community files: SECURITY.md (threat model incl. sandbox_run), bug/feature issue templates, PR template with mandatory verification evidence.
- **`record_verification` audit tool** (MCP + `guard_cli.py record`): appends JSONL entries to `${PLUGIN_DATA}/verification-log.jsonl`, giving the SDD contract's "completion report with evidence" a persistent trail. Exposed via MCP tools/list and protocol-tested.
- **Chinese/CJK hallucination tokens** in all three groups (占位/待实现/保证通过/万无一失/虚构…), matched as substrings since `\b` never fires between CJK chars; `extra_tokens` config key extends the pool at runtime per group.
- **`verify_code` line numbers**: new `suspects_detail: [{name, line}]` alongside the backward-compatible `suspects`.
- **`suppress_symbols` config / `--suppress` CLI flag**: exclude known false-positive symbol names from `verify_code`; suppressed names stay visible in the `suppressed` field.
- **`sandbox_allowed_prefixes` config key**: optional executable allowlist enforced engine-side AND in the async server path BEFORE spawning — non-matching commands are refused with exit code -10 and never executed.
- **Unknown-config-key warnings** on stderr for both the MCP server and the CLI (typo'd keys can no longer silently no-op).
- **Performance baseline** (`scripts/bench.py` + 1 MB <30 s regression gate): measured ~2.3 s total for verify+scan on a synthetic megabyte module.
- **Example fixtures** (`examples/plugins/good-plugin|broken-plugin`) exercised by tests as check_plugin conformance samples.
- **Hardened Dockerfile**: runs as unprivileged user `seed` (uid 10001) with an import-based HEALTHCHECK.
- README (en): honest language-coverage table, full configuration reference, explicit sandbox_run security warning. (zh/ja equivalents land in Unreleased.)

### Changed
- **De-duplicated the sandbox execution core** (reduces reinventing the wheel): the entire spawn→communicate→timeout→error→truncate logic lived in two places (`engine.sandbox_run` and the async `_run_sandbox_async` worker), which is also how the Windows stdin deadlock shipped silently in one path only. It now lives once in `engine._run_command`; both callers delegate, and the async path registers the live process via a new `on_proc` callback for cancellation. The duplicate `_plugin_version()` (guard_server vs `engine/audit.py`) is now a single `engine.plugin_version()` shared module. `record_verification` also gained a `checks` default so the CLI is callable.

### Fixed
- **Windows stdin-inheritance deadlock in sandbox execution** (found by the local E2E/bare-env simulation layer): children spawned while the MCP server's main thread blocked on a piped stdin inherited that handle and stalled at startup until timeout — async `sandbox_run` failed 100% of the time in this environment. Both sync (`engine.sandbox_run`) and async paths now spawn with `stdin=DEVNULL`, `close_fds=True` and `CREATE_NO_WINDOW`; regression test `test_async_sandbox_completes_normally` locks it in.
- **draft-07 tuple `items` no longer crashes either validator path**: the jsonschema route degrades to the builtin subset when Draft 2020-12 rejects a legacy schema, and the builtin subset now understands positional `items` arrays plus `additionalItems`.
- **initialize() negotiates protocolVersion**: echoes the client's requested version when supported (2024-11-05 / 2025-03-26 / 2025-06-18), otherwise falls back to 2024-11-05 instead of always replying with the baseline.
- **Python 3.9 compatibility restored for match-statement analysis**: ast.Match* node types are resolved via getattr guards (they only exist on 3.10+); regression test simulates their absence.
- **Async sandbox no longer double-executes allowed commands**: prefix policy is now a pure check (`engine._prefix_allowed`) shared by both sync and async paths instead of a probe run that actually launched the process.
- **Identity unified to the canonical home**: server.json repository.url → github.com/Morningstar202604/AgentSeed; mcpName/server name → io.github.morningstar202604/agentseed. Installers resolve releases natively from the GitHub API.

### Added
- **sandbox_run is cancellable**: long-running commands execute in a worker thread; MCP `notifications/cancelled` kills the child process and suppresses the result frame per spec, while the session stays responsive for other requests.

### Fixed
- **CLI `sandbox` no longer exits 0 when the command never ran**: command-not-found (-2) and run-failure (-9) now exit 1, so CI gating cannot mistake an unexecuted check for a pass.
- **Version chaos resolved**: test_server.py now derives the expected version from plugin.json (the declared single source of truth) instead of a hard-coded 1.3.3; server.json npm package version synced to 0.1.0. The suite is green again.
- **check_plugin false positive on relative stdio commands**: `"./bin/run.sh"` was rejected because of a list-membership bug (`"./" in command.split("/")[0:1]`); validation now uses a proper prefix check, matching what its own error message promised.
- **License unified to Apache-2.0** in plugin.json and server.json (previously "MIT" there while LICENSE/package.json said Apache-2.0).
- **MCP server forces UTF-8 on stdin/stdout** (`reconfigure`), fixing session-killing UnicodeEncodeError on Windows ANSI code pages (e.g. cp936); sandbox subprocess output decodes with `errors="replace"` instead of degrading to `-9`.
- **JSON-RPC notification handling**: notifications (frames without `id`, e.g. `notifications/cancelled`) are never answered — previously unknown ones triggered a spec-violating error reply with `id: null`.

### Added
- **Multi-platform release pipeline** (`scripts/pack.py` + `release.ps1`/`release.sh`): one command verifies plugin.json/package.json/server.json agree on version & license, builds a single deterministic zip from package.json `files`, and emits SHA256SUMS — the SAME artifact + hash goes to GitHub Releases and npm; users pin it via installer `--sha256`/`-Sha256`.
- `--check-only` mode (also enforced by new `server/test_manifests.py`) fails CI on any cross-platform manifest drift.
- Installers accept `--url ZIP_URL` / `-Url ZIP_URL` to install from any host (self-hosted, private mirrors) and `--repo` / `-Repo` to override the release repo; default remains the canonical source.
- Installers accept `--sha256 HEX` / `-Sha256 HEX` to pin release-archive integrity; without it they print an explicit supply-chain warning (downloads were previously unverified).
- CLI `verify --strict`: a source file that cannot be parsed at all becomes exit 1 under strict gating.

### Changed
- `check_plugin` now reports `skills/<dir>/ missing required SKILL.md` instead of silently skipping such directories.
- Schema fallback validator: `additionalProperties: false` also applies when the schema has no `properties` key (all keys unexpected).
- npm launcher defaults to `python` on Windows (where `python3` is normally absent); PYTHON override unchanged.
