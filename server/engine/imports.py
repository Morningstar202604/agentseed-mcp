"""AgentSeed import verification — package-hallucination (slopsquatting) guard.

Motivated by "We Have a Package for You!" (USENIX Security 2025,
arXiv:2406.10279): across 576k generated samples, LLMs invented non-existent
package names in ~5.2% (commercial) to ~21.7% (open-source) of outputs, and
~58% of those names recurred across runs — predictable enough that attackers
pre-register the exact hallucinated names with malicious payloads
("slopsquatting").

``check_imports`` flags top-level imports that are neither Python stdlib nor
in the project's ``known_packages`` allowlist, so a model-suggested phantom
package cannot reach a lockfile silently. It is a REPORT, not a hard gate:
a legit long-tail package will also be flagged for the human to confirm —
that is the intended cost. Python (AST) only; other languages return an
honest empty result.
"""

from __future__ import annotations

import ast
import json
import re
import sys

# Fallback for Python < 3.10 (``sys.stdlib_module_names`` is 3.10+): a curated
# list of the most commonly imported stdlib modules. On 3.10+ the exact set is
# used and this list is never consulted.
_STDLIB_FALLBACK = frozenset(
    {
        "abc", "argparse", "array", "ast", "asyncio", "atexit", "base64",
        "bisect", "builtins", "collections", "concurrent", "configparser",
        "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime",
        "decimal", "difflib", "enum", "errno", "functools", "gc", "getpass",
        "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib",
        "inspect", "io", "ipaddress", "itertools", "json", "logging", "math",
        "multiprocessing", "os", "pathlib", "pickle", "platform", "queue",
        "random", "re", "readline", "secrets", "shlex", "shutil", "signal",
        "site", "socket", "sqlite3", "ssl", "stat", "statistics", "string",
        "struct", "subprocess", "sys", "tempfile", "textwrap", "threading",
        "time", "timeit", "token", "tokenize", "traceback", "types", "typing",
        "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings",
        "weakref", "xml", "zipfile", "zoneinfo",
    }
)

# Common third-party packages treated as known by default (beyond stdlib).
# The full resolution for anything not listed is: user config ``known_packages``.
_DEFAULT_COMMON = frozenset(
    {
        "numpy", "pandas", "scipy", "sklearn", "matplotlib", "seaborn", "plotly",
        "requests", "httpx", "aiohttp", "urllib3", "beautifulsoup4", "bs4",
        "scrapy", "selenium", "playwright", "flask", "fastapi", "django",
        "starlette", "uvicorn", "gunicorn", "jinja2", "sqlalchemy", "pymysql",
        "psycopg2", "redis", "pymongo", "elasticsearch", "celery", "kafka",
        "pydantic", "pydantic_settings", "click", "typer", "rich", "tqdm",
        "pytest", "coverage", "black", "ruff", "mypy", "flake8", "isort",
        "tox", "nox", "hypothesis", "unittest", "jupyter", "notebook",
        "ipykernel", "ipython", "nbformat", "nbconvert", "tensorflow", "torch",
        "keras", "transformers", "datasets", "tokenizers", "accelerate",
        "sentence_transformers", "openai", "anthropic", "google", "googleapiclient",
        "boto3", "botocore", "azure", "awscli", "paramiko", "cryptography",
        "pycryptodome", "bcrypt", "jwt", "pyjwt", "passlib", "yaml", "pyyaml",
        "tomllib", "tomli", "tomlkit", "jsonschema", "setuptools", "wheel",
        "pip", "pipenv", "poetry", "uv", "pre_commit", "arrow", "pendulum",
        "dateutil", "python_dateutil", "pytz", "tzlocal", "zoneinfo", "natsort",
        "more_itertools", "toolz", "pydash", "tenacity", "structlog", "loguru",
        "colorama", "clickhouse_driver", "duckdb", "polars", "dask", "ray",
        "pillow", "python-dotenv", "python-multipart", "websockets", "grpcio",
        "protobuf", "psutil", "uvloop", "greenlet", "msgpack", "orjson",
    }
)

# npm is a different ecosystem from PyPI: scanning package.json against the
# Python-centric known set would flag nearly every real dependency, so
# manifest scanning carries its own curated common-package set. Not
# exhaustive — a legit long-tail package is expected to be flagged for human
# confirmation, same report-not-gate contract as code imports.
_NPM_COMMON = frozenset(
    {
        "react", "react-dom", "react-router", "react-router-dom", "next", "vue",
        "vue-router", "pinia", "vuex", "nuxt", "@angular/core", "@angular/cli",
        "svelte", "@sveltejs/kit", "solid-js", "preact", "express", "koa",
        "fastify", "@nestjs/core", "@nestjs/cli", "@nestjs/common", "socket.io",
        "socket.io-client", "ws", "axios", "node-fetch", "got", "superagent",
        "undici", "lodash", "ramda", "underscore", "moment", "dayjs",
        "date-fns", "uuid", "nanoid", "crypto-js", "jest", "mocha", "vitest",
        "@vitest/expect", "chai", "sinon", "playwright", "@playwright/test",
        "puppeteer", "cypress", "eslint", "prettier", "typescript", "webpack",
        "webpack-cli", "vite", "rollup", "esbuild", "swc", "@swc/core",
        "@babel/core", "@babel/preset-env", "@babel/cli", "ts-node", "tsx",
        "ts-jest", "nodemon", "concurrently", "cross-env", "dotenv", "zod",
        "yup", "joi", "ajv", "class-validator", "class-transformer", "mongoose",
        "sequelize", "prisma", "@prisma/client", "typeorm", "knex", "objection",
        "redis", "ioredis", "amqplib", "kafkajs", "graphql", "apollo-server",
        "@apollo/client", "@apollo/server", "trpc", "@trpc/server",
        "@trpc/client", "commander", "yargs", "inquirer", "prompts", "chalk",
        "ora", "debug", "pino", "winston", "morgan", "cors", "helmet",
        "body-parser", "cookie-parser", "compression", "jsonwebtoken", "bcrypt",
        "bcryptjs", "passport", "multer", "js-yaml", "yaml", "cheerio", "jsdom",
        "marked", "tailwindcss", "sass", "less", "postcss", "autoprefixer",
        "bootstrap", "antd", "@mui/material", "@mui/icons-material",
        "styled-components", "@emotion/react", "@emotion/styled", "redux",
        "@reduxjs/toolkit", "@tanstack/react-query", "zustand", "mobx", "rxjs",
        "three", "d3", "chart.js", "glob", "fs-extra", "rimraf", "shelljs",
        "execa", "semver", "tar", "rimble", "open", "env-paths",
    }
)

_MANIFEST_KINDS = ("requirements", "pyproject", "package.json")


def _stdlib_modules() -> frozenset[str]:
    names = getattr(sys, "stdlib_module_names", None)
    return frozenset(names) if names is not None else _STDLIB_FALLBACK


def _pypi_normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def _imported_top_level(source: str) -> list[tuple[str, int]]:
    """(top-level module name, lineno) for every import / from-import."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.append((node.module.split(".")[0], node.lineno))
    return out


def check_imports(
    source: str,
    language: str = "python",
    known_packages: list[str] | None = None,
) -> dict:
    """Flag top-level imports neither in stdlib nor in the known-package set.

    ``known_packages`` (config key of the same name) extends the default
    common third-party allowlist with project-local packages. Python only
    (AST); other languages return an honest empty result.

    Returns:
        {"language", "imports_ok", "suspicious": [{"package", "line"}, ...],
         "note"}
    """
    lang = (language or "python").strip().lower()
    if lang != "python":
        return {
            "language": lang,
            "imports_ok": True,
            "suspicious": [],
            "note": "Import verification is implemented for python (AST); "
            "other languages are not covered yet.",
        }
    known = set(_DEFAULT_COMMON)
    for pkg in known_packages or []:
        if isinstance(pkg, str) and pkg.strip():
            known.add(pkg.strip())
    stdlib = _stdlib_modules()
    suspicious = [
        {"package": pkg, "line": line}
        for pkg, line in _imported_top_level(source)
        if pkg not in stdlib and pkg not in known
    ]
    note = (
        "Top-level import is neither Python stdlib nor in the known-package "
        "set (stdlib + common third-party + config `known_packages`) — a "
        "possible hallucinated package (slopsquatting). Verify the name exists "
        "in the registry before installing. This is a report, not a gate."
    )
    return {
        "language": "python",
        "imports_ok": not suspicious,
        "suspicious": suspicious,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Dependency-manifest scanning — the slopsquatting FIRST CONTACT surface.
#
# An import check sees code that already exists; a model's hallucinated
# package usually enters the project through a manifest edit BEFORE any code
# imports it ("We Have a Package for You!", USENIX Security 2025:
# arXiv:2406.10279). Same report-not-gate contract, zero dependencies.
# Parsing is a deliberately honest subset: requirements lines, PEP 621
# [project] dependency arrays, Poetry dependency sections, and package.json
# dependency objects. Everything else degrades to fewer entries, never to a
# false clean claim — the note says so.
# ---------------------------------------------------------------------------

_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")

_TOML_QUOTED_RE = re.compile(r'"([^"]+)"')
_TOML_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def manifest_kind_for_path(path: str) -> str | None:
    base = re.sub(r"\s", "", path).split("/")[-1].split("\\")[-1].lower()
    if base.startswith("requirements") and base.endswith(".txt"):
        return "requirements"
    if base.startswith("constraints") and base.endswith(".txt"):
        return "requirements"
    if base == "pyproject.toml":
        return "pyproject"
    if base == "package.json":
        return "package.json"
    return None


def _guess_manifest_kind(text: str) -> str | None:
    head = text.lstrip()
    if head.startswith("{"):
        return "package.json"
    if "[project]" in text or "[tool.poetry" in text:
        return "pyproject"
    if _REQ_NAME_RE.match(head):
        return "requirements"
    return None


def _parse_requirements(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = _REQ_NAME_RE.match(line)
        if m:
            out.append((m.group(1), lineno))
    return out


def _parse_pyproject(text: str) -> list[tuple[str, int]]:
    """PEP 621 dependency arrays + Poetry dependency sections (honest subset)."""
    out: list[tuple[str, int]] = []
    section = ""
    in_array = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        header = _TOML_SECTION_RE.match(line)
        if header:
            section = header.group(1).strip()
            in_array = False
            continue
        collecting = section == "project" and (
            line.startswith("dependencies") or line.startswith("optional-dependencies")
        )
        poetry = section.startswith("tool.poetry") and section.endswith("dependencies")
        if in_array or collecting:
            for quoted in _TOML_QUOTED_RE.findall(line):
                m = _REQ_NAME_RE.match(quoted)
                if m:
                    out.append((m.group(1), lineno))
            if in_array:
                if line.endswith("]"):
                    in_array = False
            elif "=" in line and "[" in line:
                in_array = not line.rstrip().endswith("]")
            continue
        if poetry and "=" in line and not line.startswith("#"):
            name = line.split("=", 1)[0].strip().strip('"')
            if name and name != "python":
                out.append((name, lineno))
    return out


def _parse_package_json(text: str, name_lines: dict[str, int]) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(key)
        if isinstance(deps, dict):
            names.extend(k for k in deps if isinstance(k, str))
    for lineno, raw in enumerate(text.splitlines(), 1):
        for dep in names:
            if dep not in name_lines and f'"{dep}"' in raw:
                name_lines[dep] = lineno
    return names


def manifest_names(text: str, kind: str | None = None) -> list[str]:
    """Dependency names parsed from a manifest (the check_manifest set).

    Used by the CLI to diff a working manifest against its git-HEAD version:
    a pre-existing unknown package is the project's own history; a NEWLY
    ADDED one is what an agent just introduced — the hallucination moment.
    """
    k = (kind or "").strip().lower() or _guess_manifest_kind(text or "")
    if k not in _MANIFEST_KINDS:
        return []
    if k == "requirements":
        return [_pypi_normalize(n) for n, _ in _parse_requirements(text or "")]
    if k == "pyproject":
        return [_pypi_normalize(n) for n, _ in _parse_pyproject(text or "")]
    return _parse_package_json(text or "", {})


def check_manifest(
    text: str,
    kind: str | None = None,
    known_packages: list[str] | None = None,
    preexisting: list[str] | None = None,
) -> dict:
    """Flag manifest dependencies that are not in the known-package set.

    ``kind``: "requirements" | "pyproject" | "package.json"; inferred from
    content when omitted (or from the filename by the CLI). Known set:
    curated common packages (Python or npm per kind) + config
    ``known_packages``. Report, not a gate — same contract as
    ``check_imports``.

    ``preexisting``: names already present in the project's baseline version
    of this manifest (the CLI diffs against git HEAD). They are reported
    separately as ``preexisting_unknown`` instead of ``suspicious`` — a
    long-tail unknown the project itself depends on is not what an agent
    just hallucinated; the slopsquatting risk moment is a NEWLY ADDED name.
    Curated sets can never cover every real long-tail package, and without
    this split the report cries wolf on every honest repo.

    Returns:
        {"kind", "manifest_ok", "dependencies_checked",
         "suspicious": [{"package", "line"}, ...],
         "preexisting_unknown": [package, ...], "note"}
    """
    k = (kind or "").strip().lower() or _guess_manifest_kind(text or "")
    if k not in _MANIFEST_KINDS:
        return {
            "kind": kind,
            "manifest_ok": False,
            "dependencies_checked": 0,
            "suspicious": [],
            "preexisting_unknown": [],
            "note": "unsupported manifest kind: pass kind='requirements', "
            "'pyproject', or 'package.json' (content inference also failed)",
        }
    known_n = {_pypi_normalize(p) for p in _DEFAULT_COMMON}
    npm_known = set(_NPM_COMMON)
    for pkg in known_packages or []:
        if isinstance(pkg, str) and pkg.strip():
            known_n.add(_pypi_normalize(pkg))
            npm_known.add(pkg.strip())
    pre_n = {p.strip().lower() for p in preexisting or [] if isinstance(p, str) and p.strip()}

    if k == "requirements":
        entries = _parse_requirements(text or "")
        entries = [(_pypi_normalize(n), ln) for n, ln in entries]
        checked = entries
    elif k == "pyproject":
        checked = [(_pypi_normalize(n), ln) for n, ln in _parse_pyproject(text or "")]
    else:
        name_lines: dict[str, int] = {}
        names = _parse_package_json(text or "", name_lines)
        checked = [(n, name_lines.get(n, 0)) for n in names]

    if k == "package.json":
        suspicious = [
            {"package": n, "line": ln}
            for n, ln in checked
            if n not in npm_known and n.lower() not in pre_n
        ]
    else:
        suspicious = [
            {"package": n, "line": ln}
            for n, ln in checked
            if n and n not in known_n and n not in pre_n
        ]
    checked_names = [n for n, _ in checked]
    preexisting_unknown = [
        n for n in dict.fromkeys(checked_names) if n.lower() in pre_n
    ]
    note = (
        "Manifest dependency is not in the known-package set (curated common "
        "list + config `known_packages`) — a possible hallucinated package "
        "(slopsquatting, USENIX Security 2025). Verify the name exists in the "
        "registry before installing. Report, not a gate; parser covers "
        "requirements lines, PEP 621 dependency arrays, Poetry dependency "
        "sections and package.json dependency objects."
    )
    if pre_n:
        note += (
            f" Diff-scoped against the manifest baseline: "
            f"{len(preexisting_unknown)} pre-existing unknown package(s) are "
            "listed separately, not as suspects."
        )
    return {
        "kind": k,
        "manifest_ok": not suspicious,
        "dependencies_checked": len(checked),
        "suspicious": suspicious,
        "preexisting_unknown": preexisting_unknown,
        "note": note,
    }
