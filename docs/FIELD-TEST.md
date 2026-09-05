# Field Test — v0.6.0 real-world evidence

> Reproducibility over promises: every number below comes from a command
> listed in this document, run against real open-source repositories on the
> release candidate. Re-run them; the tables should reproduce.

- **Date:** 2026-09-06
- **Build:** AgentSeed `feature/v0.6.0-hardening` @ `6670bca` (v0.6.0)
- **Environment:** Windows 11 · Python 3.12.5 · zero optional deps installed
  (bare-stdlib engine; `verify_file` toolchain adapters unexercised here)
- **Corpus:** upstream tarballs/clones of flask (`main`), requests (`main`),
  django (`main`, 2930 `.py` files), gin (`master`, 59 non-test `.go` excluding
  the vendored `codec/`), axios (`main`, 62 `lib/*.js` + `package.json`)

## 1. Composite gate on real repositories

`python server/guard_cli.py gate --root <repo>` (conformance + symbols +
baseline scan + coverage, one exit code):

| Repository | Files checked | Suspects | Missing imports | Unparseable | Elapsed | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| flask | 83 | 0 | 0 | 0 | 0.88 s | pass |
| requests | 37 | 0 | 0 | 0 | 0.67 s | pass |
| django | 2930 | 0 | 0 | 1 | 48.3 s | fail* |
| gin (gate's symbol stage is Python-only) | 0 | — | — | — | 0.38 s | pass |
| axios (same) | 0 | — | — | — | 1.40 s | pass |

\* django's only finding is `tests/test_runner_apps/tagged/tests_syntax_error.py`
— django's own deliberately-broken fixture. A file that cannot parse IS a
finding; that is the gate working, not a false positive.

## 2. Undefined-symbol detection, engine only (`detect_undefined_symbols`)

Single-file lexical/AST analysis, no project index:

| Corpus | Files | Files with suspects |
| --- | --- | --- |
| axios `lib/*.js` | 62 | **0** |
| gin non-test `*.go` (single-file) | 54 | 36 — all cross-file definitions (`debugPrint`, `assert1`, `nameOfFunction`, ... defined in sibling files) |

With the project symbol index (`verify_in_project`, what `verify`/`gate` use):

| Corpus | Files | Files with suspects |
| --- | --- | --- |
| gin non-test `*.go` (with index) | 54 | **0** |

The single-file/index split is the designed two-tier behavior: a name defined
in a sibling file is a real missing-import bug with a different fix, and the
index is what tells the two verdicts apart.

False positives fixed on this exact corpus during the 0.6.0 field pass
(each with a regression test in `server/test_false_positives.py`):
apostrophes in comments opening multi-line bogus string spans (gin),
JSDoc text matching the bare-call pattern (axios `BF`), object destructuring
and class/object method definitions not collected, member chains split
across lines, missing Web/Node globals, `# noqa` lines and dunder protocol
names flagged (django).

## 3. Manifest scanning, diff-scoped against git HEAD

`python server/guard_cli.py imports --manifest <manifest>` on a real axios
git clone:

| Measure | Value |
| --- | --- |
| Dependencies parsed | 43 |
| Suspicious (newly added + unknown) | **0** |
| Pre-existing unknowns (reported separately) | 43 |

Without the git-HEAD baseline the same manifest lists all 43 unknowns as
suspicious — the diff-scoping exists because a project's own long-tail
dependencies are not what an agent just hallucinated. An agent adding
`fastapi-magic-auth` to a manifest is flagged as the only suspect
(regression-tested: `test_imports_manifest_diff_scopes_against_git_head`).

## 4. End-to-end drill (planted delivery)

A scratch project ("shop API") with one planted defect per class, then the
full battery:

| Planted defect | Gate that caught it | Result |
| --- | --- | --- |
| call to `paginate_records()` — defined nowhere | `verify app.py` | suspect named with line number |
| README: "All tests pass, production ready, zero downtime" | `scan README.md` | 3 error-severity oversold hits, `blocking: true` |
| `# TODO` + `placeholder` return | `scan app.py` | 2 warning-severity stub hits (reported, non-blocking) |
| agent-added `fastapi-magic-auth` dependency | `imports --manifest` | only suspect; pre-existing `fastapi`/`uvicorn` clean |
| test that exits non-zero while claiming pass | `sandbox --expect-exit 0` | `exit_met: false`, CLI exit 1 |
| changed files with no verification evidence | `gate --coverage-strict` | unverified files named; after `record --file ...` the coverage stage passes |

Not caught (honest boundary, documented in DESIGN §8): a *plausible-looking*
fabricated docs URL (`docs.fastapi-magic.dev`) — the lexical `fabricated_url`
group catches placeholder domains, reserved TLDs and fabricated "example"
domains; deciding that a plausible domain does not exist requires a registry
check (network), which is an optional-config direction, not a lexical one.

## 5. Unit/regression suite

`python -m unittest discover -s server` on the release candidate:
**304 tests, all pass** (CI additionally runs the matrix on Python
3.9–3.13 and a bare job without optional dependencies).

## 6. Reproduce

```bash
git clone https://github.com/Morningstar202604/AgentSeed.git
cd AgentSeed
# gate on any real repository
python server/guard_cli.py gate --root /path/to/flask
# symbol sweep (single-file)
python server/guard_cli.py verify /path/to/axios/lib/utils.js
# diff-scoped manifest scan (inside a git repo with a modified manifest)
python server/guard_cli.py imports --manifest /path/to/requirements.txt
# full unit suite (no dependencies needed)
python -m unittest discover -s server
```

Corpus note: upstream snapshots are dated 2026-09-06; later upstream commits
may shift file counts. The gin `codec/` directory is gin's vendored fork of a
JSON library and is excluded from the index-mode sweep; its interface-method
declarations remain a documented lexical false-positive class.
