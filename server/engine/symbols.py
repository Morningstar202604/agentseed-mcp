"""AgentSeed undefined symbol detection.

Static analysis to flag symbols the model may have hallucinated
(called/used but never defined or imported). Supports python (AST)
and typescript/javascript (lexical regex pass).
"""

from __future__ import annotations

import ast
import builtins
import difflib
import os
import re
from dataclasses import dataclass

# Optional: pyflakes for more accurate Python undefined-name detection (F821).
# When available its scope-aware analysis is merged in (e.g. ``del x`` on an
# undefined name, which the hand-rolled walk's Store/Load contexts miss).
# When unavailable, the zero-dep fallback applies unchanged.
_HAS_PYFLAKES = False
try:
    from pyflakes.checker import Checker as _PyflakesChecker
    from pyflakes.messages import UndefinedName as _PyflakesUndefinedName

    _HAS_PYFLAKES = True
except ImportError:  # pragma: no cover
    _PyflakesChecker = None
    _PyflakesUndefinedName = None


def _pyflakes_undefined(source: str) -> list[tuple[str, int]] | None:
    """Undefined-name findings via optional pyflakes, or None when pyflakes
    is unavailable or the source cannot be compiled (caller already handled
    SyntaxError separately). Returns (name, lineno) pairs."""
    if not _HAS_PYFLAKES:
        return None
    try:
        tree = compile(source, "<agentseed>", "exec", ast.PyCF_ONLY_AST)
        checker = _PyflakesChecker(tree, "<agentseed>")
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return None
    out: list[tuple[str, int]] = []
    for msg in checker.messages:
        if isinstance(msg, _PyflakesUndefinedName) and msg.message_args:
            out.append((str(msg.message_args[0]), getattr(msg, "lineno", 0)))
    return out


# ---------------------------------------------------------------------------
# TypeScript lightweight static analysis (zero-dependency regex pass).
# ---------------------------------------------------------------------------

TS_GLOBALS = {
    "console",
    "Math",
    "JSON",
    "Object",
    "Array",
    "String",
    "Number",
    "Boolean",
    "Date",
    "Promise",
    "RegExp",
    "Error",
    "Set",
    "Map",
    "Symbol",
    "BigInt",
    "process",
    "global",
    "window",
    "document",
    "module",
    "exports",
    "require",
    "fetch",
    "setTimeout",
    "setInterval",
    "clearTimeout",
    "clearInterval",
    "parseInt",
    "parseFloat",
    "isNaN",
    "isFinite",
    "encodeURIComponent",
    "decodeURIComponent",
    "encodeURI",
    "decodeURI",
    "undefined",
    "NaN",
    "Infinity",
    # Web/Node globals real code calls every day (axios http adapter flagged
    # URL/Uint8Array/TypeError before these were added)
    "globalThis",
    "URL",
    "URLSearchParams",
    "Reflect",
    "Proxy",
    "WeakMap",
    "WeakSet",
    "WeakRef",
    "Intl",
    "TypeError",
    "RangeError",
    "EvalError",
    "ReferenceError",
    "SyntaxError",
    "URIError",
    "ArrayBuffer",
    "SharedArrayBuffer",
    "Uint8Array",
    "Uint8ClampedArray",
    "Int8Array",
    "Uint16Array",
    "Int16Array",
    "Uint32Array",
    "Int32Array",
    "Float32Array",
    "Float64Array",
    "BigInt64Array",
    "BigUint64Array",
    "DataView",
    "TextEncoder",
    "TextDecoder",
    "AbortController",
    "AbortSignal",
    "Blob",
    "File",
    "FileReader",
    "FormData",
    "Headers",
    "Request",
    "Response",
    "WebSocket",
    "Worker",
    "Event",
    "EventTarget",
    "CustomEvent",
    "MessageChannel",
    "BroadcastChannel",
    "crypto",
    "atob",
    "btoa",
    "structuredClone",
    "queueMicrotask",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "setImmediate",
    "clearImmediate",
    "caches",
    "navigator",
    "location",
    "self",
    "history",
    "localStorage",
    "sessionStorage",
    "XMLHttpRequest",
    "ReadableStream",
    "WritableStream",
    "TransformStream",
    "DOMException",
    "escape",
    "unescape",
    "Buffer",
    "performance",
}

TS_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "typeof",
    "instanceof",
    "function",
    "class",
    "interface",
    "import",
    "export",
    "const",
    "let",
    "var",
    "new",
    "delete",
    "in",
    "of",
    "await",
    "yield",
    "throw",
    "try",
    "do",
    "case",
    "default",
    "else",
    "this",
    "super",
    "void",
    "break",
    "continue",
    "as",
    "from",
    "type",
    "extends",
    "implements",
    "public",
    "private",
    "protected",
    "readonly",
    "static",
    "async",
    "keyof",
    "never",
    "unknown",
    "any",
}

_TS_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"

# The TS/JS native pass used to scan raw source: a JSDoc line like
# "This catches EF BB BF (the UTF-8 BOM)" matched the bare-call pattern and
# flagged "BF" on real code (axios). Mask strings and comments first — the
# same discipline the generic registry engine already follows. Built lazily
# because LangSpec is defined below the functions that use it.
_TS_MASK_SPEC: LangSpec | None = None


def _mask_ts(source: str) -> str:
    global _TS_MASK_SPEC
    if _TS_MASK_SPEC is None:
        _TS_MASK_SPEC = LangSpec(
            name="_ts_mask",
            line_comments=("//",),
            block_comments=(("/*", "*/"),),
            strings=(
                r'"(?:[^"\\\n]|\\.)*"',
                r"'(?:[^'\\\n]|\\.)*'",
                r"`(?:[^`\\]|\\.)*`",
            ),
        )
    return _mask_source(source, _TS_MASK_SPEC)


def _deduplicate(items: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _ts_defined_symbols(source: str) -> set[str]:
    """Collect identifiers defined or imported in a TS/JS source (lexical pass)."""
    source = _mask_ts(source)
    defined: set[str] = set(TS_GLOBALS)
    # import { a, b as c } from '...'
    for m in re.finditer(r"\bimport\s*\{([^}]*)\}\s*from", source):
        for part in m.group(1).split(","):
            p = part.strip()
            if not p:
                continue
            alias = re.search(r"\bas\s+(" + _TS_IDENT + r")\s*$", p)
            defined.add(alias.group(1) if alias else p.split(":")[-1].strip())
    # import a / import * as a / import a = require()
    for m in re.finditer(r"\bimport\s+(?:\*\s+as\s+)?(" + _TS_IDENT + r")\s*(?:from|=)", source):
        defined.add(m.group(1))
    # const { a, b: c } = require(...) / import(...) / destructuring
    for m in re.finditer(
        r"\b(?:const|let|var)\s*\{([^}]*)\}\s*=\s*(?:require|import)\s*\(", source
    ):
        for part in m.group(1).split(","):
            p = part.strip()
            if not p:
                continue
            alias = re.search(r":\s*(" + _TS_IDENT + r")\s*$", p)
            defined.add(alias.group(1) if alias else p.split(":")[0].strip())
    # const [count, setCount] = useState(0) — array destructuring from ANY
    # initializer (the React hook idiom above all). Without this, every hook
    # setter was flagged as a hallucinated call.
    for m in re.finditer(r"\b(?:const|let|var)\s*\[([^\]]*)\]\s*=", source):
        for part in m.group(1).split(","):
            p = re.sub(r"^\.\.\.", "", part.strip())
            p = p.split("=")[0].strip()
            if re.fullmatch(_TS_IDENT, p):
                defined.add(p)
    # const { a, b: c, d = 1, ...rest } = anyExpr — object destructuring from
    # ANY initializer (React props destructuring, `const {getPrototypeOf} =
    # Object`), not just require/import. Without this, idiomatic real-world
    # code (axios) produced suspects on every destructure.
    for m in re.finditer(r"\b(?:const|let|var)\s*\{([^{}]*)\}\s*=", source):
        for part in m.group(1).split(","):
            p = re.sub(r"^\.\.\.", "", part.strip())
            if not p:
                continue
            alias = re.search(r":\s*(" + _TS_IDENT + r")", p)
            name = alias.group(1) if alias else p.split(":")[0]
            name = name.split("=")[0].strip()
            if re.fullmatch(_TS_IDENT, name):
                defined.add(name)
    # function/class/interface/type declarations
    for m in re.finditer(
        r"\b(?:async\s+)?(?:function|class|interface|type|enum)\s+(" + _TS_IDENT + r")",
        source,
    ):
        defined.add(m.group(1))
    # const/let/var declarations
    for m in re.finditer(r"\b(?:const|let|var)\s+([^;\n]+)", source):
        for part in m.group(1).split(","):
            decl = re.match(r"\s*(" + _TS_IDENT + r")(?:\s*[:=]|\s*$)", part)
            if decl:
                defined.add(decl.group(1))

    def _add_params(body: str) -> None:
        for part in re.split(r",", body):
            p = part.strip()
            if not p:
                continue
            p = re.sub(r":.*$", "", p)
            p = re.sub(r"^\.\.\.", "", p)
            p = re.sub(r"^\{|\}$", "", p)
            p = re.sub(r"^\[|\]$", "", p)
            if re.fullmatch(_TS_IDENT, p):
                defined.add(p)

    for m in re.finditer(r"\bfunction\s+(?:" + _TS_IDENT + r"\s*)?\(([^)]*)\)", source):
        _add_params(m.group(1))
    # class/object method definitions: `constructor(x) {`,
    # `getSession(authority, options) {`, `async run() {` — a definition site
    # looks exactly like a bare call to the call-scan, so real-world classes
    # (axios Axios.js) flagged constructor/request/_request. Line-anchored so
    # call sites are not swept in; keyword matches (if/for/while) are
    # harmless. The parameter list is collected too — method params
    # (`forEach(fn) { fn(h) }`) were otherwise flagged as bare calls.
    for m in re.finditer(
        r"(?m)^[ \t]*(?:static\s+|async\s+|get\s+|set\s+|\*\s*)*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{",
        source,
    ):
        defined.add(m.group(1))
        _add_params(m.group(2))
    for m in re.finditer(
        r"\b(?:const|let|var)\s+" + _TS_IDENT + r"\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
        source,
    ):
        _add_params(m.group(1))
    for m in re.finditer(
        r"\b(?:const|let|var)\s+" + _TS_IDENT + r"\s*=\s*(?:async\s*)?(" + _TS_IDENT + r")\s*=>",
        source,
    ):
        _add_params(m.group(1))
    # params of arrows assigned to anything: `lookup = (hostname, opt, cb) =>`
    # (reassignment to an existing variable, property or element LHS)
    for m in re.finditer(
        r"(?m)^[ \t]*[A-Za-z_$][\w$.\[\]]*\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
        source,
    ):
        _add_params(m.group(1))
    return defined


def _detect_ts_undefined(source: str) -> tuple[list[str], str]:
    """Lexical pass: calls/new-expressions whose callee is never defined."""
    source = _mask_ts(source)
    defined = _ts_defined_symbols(source)
    suspects: list[str] = []
    # Line-based so a member chain split across lines — prettier style
    # `encode(value).\n  replace(/x/g, ':')` — is not misread as a bare
    # `replace(...)` call (buildURL.js real-world false positive). A line
    # whose call shape follows a previous line ending in "." is a member
    # continuation, not a bare call.
    prev_ends_dot = False
    for line in source.splitlines():
        stripped = line.strip()
        chained = prev_ends_dot and bool(re.match(r"[A-Za-z_$]", stripped))
        prev_ends_dot = stripped.endswith((".", "?."))
        if chained:
            continue
        for m in re.finditer(r"\bnew\s+(" + _TS_IDENT + r")\s*\(", line):
            name = m.group(1)
            if name not in defined and name not in TS_KEYWORDS:
                suspects.append(name)
        for m in re.finditer(r"(?<![\w$.])(" + _TS_IDENT + r")\s*\(", line):
            name = m.group(1)
            if name not in defined and name not in TS_KEYWORDS:
                suspects.append(name)
    note = (
        "Lexical regex pass, not a type checker; may miss destructured "
        "imports or produce false positives on dynamic/global references."
    )
    return _deduplicate(suspects), note


# ---------------------------------------------------------------------------
# Generic multi-language lexical verification (config-driven language
# registry). Every registered language is analyzed by the SAME engine:
# comments/strings are masked, defined symbols are collected from the
# per-language patterns, then bare calls / `new` expressions are checked.
# Adding a language is a LangSpec config change, not a code change — this
# is how verify_code scales to "any language" without a parser per language.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LangSpec:
    name: str
    aliases: tuple[str, ...] = ()
    line_comments: tuple[str, ...] = ()
    block_comments: tuple[tuple[str, str], ...] = ()
    strings: tuple[str, ...] = ()
    ident: str = r"[A-Za-z_][A-Za-z0-9_]*"
    keywords: frozenset[str] = frozenset()
    globals_: frozenset[str] = frozenset()
    # Each pattern must have exactly ONE capturing group: the defined name(s),
    # which may be comma-separated (e.g. `var a, b = ...`).
    defn_patterns: tuple[str, ...] = ()
    import_patterns: tuple[str, ...] = ()
    # Patterns whose group(1) is a function parameter list body, e.g. "a int, b string".
    param_patterns: tuple[str, ...] = ()
    # How to pick the parameter NAME from one comma-part:
    #   "last"         -> `Type name` (C/Java/C#/C++/PHP)
    #   "first"        -> `name Type` (Go) or bare `name` (Ruby)
    #   "before_colon" -> `name: Type` (Rust/Kotlin/Swift)
    param_mode: str = "last"
    # Characters masked to spaces before analysis (e.g. PHP "$" variable sigil).
    strip_chars: str = ""
    # Ruby-style languages allow bare method calls without parentheses;
    # standalone undefined identifiers are then flagged as calls too.
    bare_calls: bool = False
    # File suffixes for this language. The CLI's path-vs-inline heuristic and
    # the tree walker derive their extension sets from the registry, so a
    # language that declares no suffixes is invisible to `gate`/`scan`.
    extensions: tuple[str, ...] = ()


_LANG_REGISTRY: dict[str, LangSpec] = {}
_LANG_ALIASES: dict[str, str] = {}

# Languages with a dedicated analyzer instead of the generic lexical pass.
# Declared as data so that dispatch, the supported-language surface and the
# file-extension sets are all derived from one place — the old shape
# (`if language in ("typescript", "ts", ...)`) had to be edited in every
# function that touched a language and was already stale there.
_NATIVE_LANGS: dict[str, dict] = {
    "python": {
        "mode": "ast",
        "aliases": ("python", "py"),
        "extensions": (".py", ".pyi"),
    },
    "typescript": {
        "mode": "ts_lexical",
        "aliases": ("typescript", "ts", "tsx"),
        "extensions": (".ts", ".tsx", ".mts", ".cts"),
    },
    "javascript": {
        "mode": "ts_lexical",
        "aliases": ("javascript", "js", "jsx"),
        "extensions": (".js", ".jsx", ".mjs", ".cjs"),
    },
}

_NATIVE_BY_ALIAS: dict[str, tuple[str, str]] = {
    alias: (name, cfg["mode"]) for name, cfg in _NATIVE_LANGS.items() for alias in cfg["aliases"]
}


def native_language(name: str) -> tuple[str, str] | None:
    """Return ``(canonical, mode)`` for a natively-analyzed language, else None."""
    if not name:
        return None
    return _NATIVE_BY_ALIAS.get(name.strip().lower())


def _register_lang(spec: LangSpec) -> None:
    _LANG_REGISTRY[spec.name] = spec
    _LANG_ALIASES[spec.name] = spec.name
    for alias in spec.aliases:
        _LANG_ALIASES[alias] = spec.name


def resolve_language(name: str) -> LangSpec | None:
    """Map a user-supplied language name to a registered spec (or None)."""
    if not name:
        return None
    canonical = _LANG_ALIASES.get(name.strip().lower())
    return _LANG_REGISTRY.get(canonical) if canonical else None


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge overlapping [start, end) spans."""
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for s, e in ordered[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _mask_source(source: str, spec: LangSpec) -> str:
    """Blank out strings and comments so patterns only see real code."""
    spans: list[tuple[int, int]] = []
    for pat in spec.strings:
        for m in re.finditer(pat, source):
            spans.append((m.start(), m.end()))
    for lc in spec.line_comments:
        for m in re.finditer(re.escape(lc) + r"[^\r\n]*", source):
            spans.append((m.start(), m.end()))
    for start, end in spec.block_comments:
        for m in re.finditer(re.escape(start) + r".*?" + re.escape(end), source, re.DOTALL):
            spans.append((m.start(), m.end()))
    buf = list(source)
    for s, e in _merge_spans(spans):
        for i in range(s, min(e, len(buf))):
            if buf[i] not in "\r\n":  # keep line structure for readability
                buf[i] = " "
    out = "".join(buf)
    for ch in spec.strip_chars:
        out = out.replace(ch, " ")
    return out


def _collect_names(m: re.Match, spec: LangSpec) -> list[str]:
    """Names captured by a defn/import pattern (group 1 may be comma-separated)."""
    out: list[str] = []
    for g in m.groups():
        if not g:
            continue
        for part in g.split(","):
            name = part.strip()
            if name and re.fullmatch(spec.ident, name):
                out.append(name)
    return out


def _params_from(body: str, spec: LangSpec) -> list[str]:
    """Pick parameter names out of one comma-part per the spec's param_mode."""
    if spec.param_mode == "before_colon":
        m = re.search(r"([A-Za-z_]\w*)\s*:", body)
        return [m.group(1)] if m else []
    if spec.param_mode == "first":
        idents = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", body)
        return idents[:1]
    # "last": drop default-value initializers (`int x = foo()`) first
    head = body.split("=", 1)[0]
    idents = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", head)
    return idents[-1:] if idents else []


def _generic_defined(source: str, spec: LangSpec) -> set[str]:
    """Collect everything a generic language source defines or imports."""
    defined = set(spec.globals_)
    for pat in spec.import_patterns:
        for m in re.finditer(pat, source):
            defined.update(_collect_names(m, spec))
    for pat in spec.defn_patterns:
        for m in re.finditer(pat, source):
            defined.update(_collect_names(m, spec))
    for pat in spec.param_patterns:
        for m in re.finditer(pat, source):
            for name in _params_from(m.group(1), spec):
                defined.add(name)
    return defined


def _generic_detect_undefined(source: str, spec: LangSpec) -> tuple[list[str], str]:
    """Lexical pass shared by every registered language (see LangSpec)."""
    masked = _mask_source(source, spec)
    defined = _generic_defined(masked, spec)
    suspects: list[str] = []
    ident = spec.ident
    for m in re.finditer(r"\bnew\s+(" + ident + r")\s*\(", masked):
        name = m.group(1)
        if name not in defined and name not in spec.keywords:
            suspects.append(name)
    # lookbehind blocks attribute (`obj.m()`, `obj->m()`), path (`a::b()`),
    # and `$`-prefixed calls so only bare calls are checked
    for m in re.finditer(r"(?<![\w$.>:-@])(" + ident + r")\s*\(", masked):
        name = m.group(1)
        if name not in defined and name not in spec.keywords:
            suspects.append(name)
    # languages that allow paren-less method calls (Ruby): flag standalone
    # undefined identifiers, while excluding attribute/symbol/definition sites
    if spec.bare_calls:
        for m in re.finditer(r"(?<![\w$.@:>-])([A-Za-z_]\w*)(?![\w$.@:(=])", masked):
            name = m.group(1)
            if name not in defined and name not in spec.keywords:
                suspects.append(name)
    note = (
        f"Generic lexical pass for {spec.name} (config-driven registry); "
        "not a type checker — attribute calls, macros, and cross-file "
        "symbols are not analyzed."
    )
    return _deduplicate(suspects), note


_register_lang(
    LangSpec(
        name="go",
        extensions=(".go",),
        aliases=("golang",),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"`[^`]*`", r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "package", "import", "func", "var", "const", "type", "struct",
                "interface", "map", "chan", "go", "defer", "select", "range",
                "return", "if", "else", "for", "switch", "case", "default",
                "break", "continue", "fallthrough", "goto", "panic", "recover",
                "nil", "true", "false", "iota", "len", "cap", "make", "new",
                "append", "copy", "delete", "close", "complex", "real", "imag",
                "min", "max", "print", "println", "error", "byte", "rune",
                "int", "int8", "int16", "int32", "int64", "uint", "uint8",
                "uint16", "uint32", "uint64", "uintptr", "float32", "float64",
                "string", "bool", "any",
            }
        ),
        defn_patterns=(
            r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(",
            r"\btype\s+([A-Za-z_]\w*)",
            r"\bvar\s+([A-Za-z_]\w*)",
            r"\bconst\s+([A-Za-z_]\w*)",
            r"([A-Za-z_]\w*)\s*:=",
        ),
        param_patterns=(r"\bfunc\s+(?:\([^)]*\)\s*)?[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="first",
    )
)

_register_lang(
    LangSpec(
        name="rust",
        extensions=(".rs",),
        aliases=("rs",),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "fn", "let", "mut", "const", "static", "struct", "enum",
                "trait", "impl", "use", "mod", "pub", "crate", "self", "Self",
                "super", "if", "else", "match", "while", "loop", "for", "in",
                "return", "break", "continue", "move", "ref", "type", "where",
                "async", "await", "dyn", "unsafe", "extern", "as", "true",
                "false", "Option", "Result", "Some", "None", "Ok", "Err",
                "Vec", "String", "Box", "Rc", "Arc", "i8", "i16", "i32",
                "i64", "i128", "isize", "u8", "u16", "u32", "u64", "u128",
                "usize", "f32", "f64", "bool", "char", "str", "println",
                "print", "eprintln", "eprint", "panic", "assert", "assert_eq",
                "assert_ne", "vec", "format", "dbg", "todo", "unimplemented",
                "unreachable", "macro_rules",
            }
        ),
        defn_patterns=(
            r"\bfn\s+([A-Za-z_]\w*)\s*\(",
            r"\bstruct\s+([A-Za-z_]\w*)",
            r"\benum\s+([A-Za-z_]\w*)",
            r"\btrait\s+([A-Za-z_]\w*)",
            r"\bconst\s+([A-Za-z_]\w*)\s*:",
            r"\bstatic\s+(?:mut\s+)?([A-Za-z_]\w*)\s*:",
            r"\blet\s+(?:mut\s+)?([A-Za-z_]\w*)\s*[=:]",
        ),
        import_patterns=(
            r"\buse\s+(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*;",
            r"\buse\s+(?:[A-Za-z_]\w*::)*\{([^}]*)\}",
        ),
        param_patterns=(r"\bfn\s+[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="before_colon",
    )
)

_register_lang(
    LangSpec(
        name="java",
        extensions=(".java",),
        aliases=(),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "public", "private", "protected", "static", "final", "void",
                "int", "long", "float", "double", "boolean", "char", "byte",
                "short", "class", "interface", "enum", "extends", "implements",
                "import", "package", "new", "return", "if", "else", "for",
                "while", "do", "switch", "case", "default", "break",
                "continue", "try", "catch", "finally", "throw", "throws",
                "this", "super", "abstract", "synchronized", "native",
                "transient", "volatile", "instanceof", "true", "false", "null",
                "String", "System", "Math", "Object", "Integer", "Long",
                "Double", "Boolean", "Character", "List", "Map", "Set",
                "ArrayList", "HashMap", "HashSet", "Optional", "StringBuilder",
                "Thread", "Exception", "RuntimeException", "Iterable",
                "Collection", "Stream",
            }
        ),
        defn_patterns=(
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\binterface\s+([A-Za-z_]\w*)",
            r"\benum\s+([A-Za-z_]\w*)",
            r"(?:(?:public|private|protected|static|final|abstract|synchronized|native)\s+)*(?:[A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(",
            r"(?:(?:public|private|protected|static|final|volatile|transient)\s+)*(?:[A-Za-z_]\w*)(?:\[\])?\s+([A-Za-z_]\w*)\s*(?:=|;)",
        ),
        import_patterns=(
            r"\bimport\s+(?:static\s+)?(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)\s*;",
        ),
        param_patterns=(
            r"(?:[A-Za-z_]\w*)(?:\[\])?\s+[A-Za-z_]\w*\s*\(([^)]*)\)",
        ),
        param_mode="last",
    )
)

_register_lang(
    LangSpec(
        name="c",
        extensions=(".c", ".h"),
        aliases=(),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "auto", "break", "case", "char", "const", "continue",
                "default", "do", "double", "else", "enum", "extern", "float",
                "for", "goto", "if", "inline", "int", "long", "register",
                "restrict", "return", "short", "signed", "sizeof", "static",
                "struct", "switch", "typedef", "union", "unsigned", "void",
                "volatile", "while", "NULL", "size_t", "printf", "scanf",
                "malloc", "calloc", "free", "realloc", "memcpy", "memset",
                "strlen", "strcmp", "strcpy", "strncpy", "strcat", "sprintf",
                "snprintf", "fopen", "fclose", "fprintf", "fgets", "fputs",
                "exit", "assert", "getchar", "putchar", "puts",
            }
        ),
        defn_patterns=(
            r"\b(?:void|int|char|long|float|double|short|unsigned|signed|size_t|ssize_t|[A-Za-z_]\w*_t)\s+([A-Za-z_]\w*)\s*\(",
            r"\bstruct\s+([A-Za-z_]\w*)",
            r"\btypedef\s+(?:[A-Za-z_]\w*\s+)+([A-Za-z_]\w*)\s*;",
            r"#define\s+([A-Za-z_]\w*)",
        ),
        import_patterns=(r"#include\s*[<\"]([A-Za-z_]\w*)[>\"]",),
        param_patterns=(
            r"\b(?:void|int|char|long|float|double|short|unsigned|signed|size_t|ssize_t|[A-Za-z_]\w*_t)\s+[A-Za-z_]\w*\s*\(([^)]*)\)",
        ),
        param_mode="last",
    )
)

_register_lang(
    LangSpec(
        name="cpp",
        extensions=(".cc", ".cpp", ".cxx", ".c++", ".hpp", ".hh", ".hxx"),
        aliases=("c++", "cc", "cxx"),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "auto", "break", "case", "char", "class", "const", "constexpr",
                "continue", "default", "delete", "do", "double", "else",
                "enum", "explicit", "extern", "float", "for", "friend", "goto",
                "if", "inline", "int", "long", "namespace", "new", "noexcept",
                "nullptr", "operator", "private", "protected", "public",
                "register", "return", "short", "signed", "sizeof", "static",
                "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
                "struct", "switch", "template", "typename", "typedef", "union",
                "unsigned", "using", "virtual", "override", "void", "volatile",
                "while", "true", "false", "this", "NULL", "nullptr", "size_t",
                "std", "cout", "cin", "endl", "vector", "string", "map",
                "set", "shared_ptr", "unique_ptr", "make_shared", "make_unique",
                "printf", "malloc", "calloc", "free", "realloc", "memcpy",
                "memset", "strlen", "strcmp", "strcpy", "assert",
            }
        ),
        defn_patterns=(
            r"\b(?:[A-Za-z_]\w*)(?:::\s*[A-Za-z_]\w*)?\s+([A-Za-z_]\w*)\s*\(",
            r"\b(?:[A-Za-z_]\w*)(?:::\s*[A-Za-z_]\w*)?\s+([A-Za-z_]\w*)\s*(?:=|;)",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\bstruct\s+([A-Za-z_]\w*)",
            r"\bnamespace\s+([A-Za-z_]\w*)",
            r"\btypedef\s+(?:[A-Za-z_]\w*\s+)+([A-Za-z_]\w*)\s*;",
            r"#define\s+([A-Za-z_]\w*)",
        ),
        import_patterns=(r"#include\s*[<\"]([A-Za-z_]\w*)[>\"]",),
        param_patterns=(
            r"\b(?:void|int|char|long|float|double|short|unsigned|signed|size_t|ssize_t|bool|[A-Za-z_]\w*_t)\s+[A-Za-z_]\w*\s*\(([^)]*)\)",
        ),
        param_mode="last",
    )
)

_register_lang(
    LangSpec(
        name="csharp",
        extensions=(".cs",),
        aliases=("cs", "c#"),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'@"(?:[^"]|"")*"', r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "using", "namespace", "class", "interface", "enum", "struct",
                "public", "private", "protected", "internal", "static",
                "readonly", "const", "void", "int", "string", "bool",
                "double", "float", "long", "short", "byte", "char", "object",
                "var", "new", "return", "if", "else", "for", "foreach",
                "while", "do", "switch", "case", "default", "break",
                "continue", "try", "catch", "finally", "throw", "this",
                "base", "async", "await", "task", "delegate", "event",
                "override", "virtual", "abstract", "sealed", "partial",
                "get", "set", "null", "true", "false", "Console", "String",
                "Math", "List", "Dictionary", "IEnumerable", "Task",
                "Exception", "dynamic", "lock",
            }
        ),
        defn_patterns=(
            r"(?:(?:public|private|protected|internal|static|readonly|virtual|override|abstract|async|sealed|partial)\s+)*(?:void|int|string|bool|double|float|long|short|byte|char|object|var|[A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\binterface\s+([A-Za-z_]\w*)",
            r"\benum\s+([A-Za-z_]\w*)",
            r"\bstruct\s+([A-Za-z_]\w*)",
            r"\bnamespace\s+([A-Za-z_]\w*)",
            r"(?:(?:public|private|protected|internal|static|readonly|const)\s+)*(?:int|string|bool|double|float|long|short|byte|char|object|var|[A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(?:=|;)",
        ),
        import_patterns=(r"\busing\s+(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)\s*;",),
        param_patterns=(
            r"(?:(?:public|private|protected|internal|static|readonly|virtual|override|abstract|async|sealed|partial)\s+)*(?:void|int|string|bool|double|float|long|short|byte|char|object|var|[A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*\(([^)]*)\)",
        ),
        param_mode="last",
    )
)

_register_lang(
    LangSpec(
        name="php",
        extensions=(".php",),
        aliases=(),
        line_comments=("//", "#"),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\]|\\.)*'", r"`[^`]*`"),
        keywords=frozenset(
            {
                "function", "class", "interface", "trait", "enum", "public",
                "private", "protected", "static", "final", "abstract",
                "extends", "implements", "use", "namespace", "new", "return",
                "if", "else", "elseif", "for", "foreach", "while", "do",
                "switch", "case", "default", "break", "continue", "try",
                "catch", "finally", "throw", "this", "self", "parent", "echo",
                "print", "isset", "empty", "unset", "die", "exit", "require",
                "include", "require_once", "include_once", "global", "const",
                "var", "true", "false", "null", "array", "list", "match",
                "fn", "and", "or", "xor", "not", "as", "instanceof",
                "yield", "from", "clone",
            }
        ),
        defn_patterns=(
            r"\bfunction\s+&?\s*([A-Za-z_]\w*)\s*\(",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\binterface\s+([A-Za-z_]\w*)",
            r"\btrait\s+([A-Za-z_]\w*)",
            r"\benum\s+([A-Za-z_]\w*)",
            r"\bnamespace\s+([A-Za-z_]\w*)",
            r"(?:^|[;\s{}])([A-Za-z_]\w*)\s*=",
        ),
        import_patterns=(r"\buse\s+(?:[A-Za-z_]\w*\\)*([A-Za-z_]\w*)\s*;",),
        param_patterns=(r"\bfunction\s+(?:&?\s*[A-Za-z_]\w*\s*)?\(([^)]*)\)",),
        param_mode="last",
        strip_chars="$",
    )
)

_register_lang(
    LangSpec(
        name="ruby",
        extensions=(".rb",),
        aliases=("rb",),
        line_comments=("#",),
        block_comments=(("=begin", "=end"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\]|\\.)*'", r"`[^`]*`"),
        keywords=frozenset(
            {
                "def", "class", "module", "end", "if", "elsif", "else",
                "unless", "while", "until", "for", "in", "do", "case",
                "when", "then", "return", "break", "next", "redo", "retry",
                "yield", "raise", "rescue", "ensure", "begin", "require",
                "include", "extend", "attr_accessor", "attr_reader",
                "attr_writer", "new", "self", "super", "true", "false",
                "nil", "and", "or", "not", "lambda", "proc", "puts", "print",
                "p", "gets", "require_relative", "alias", "undef", "defined",
                "loop",
            }
        ),
        defn_patterns=(
            r"\bdef\s+(?:self\.)?([A-Za-z_]\w*)",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\bmodule\s+([A-Za-z_]\w*)",
            # Local-variable assignments. bare_calls flags every bare
            # identifier, so a missing assignment collector turned ordinary
            # `sum += i` / `x = compute` locals into false suspects.
            r"\b([A-Za-z_]\w*)\s*(?:&&|\|\||[+\-*/%])?=(?![=~])",
            # Block parameters: each { |i| ... }, each do |acc, item| ... end
            r"\|([^|\n]*)\|",
        ),
        import_patterns=(r"\brequire\s+['\"]([A-Za-z_]\w*)['\"]",),
        param_patterns=(r"\bdef\s+(?:self\.)?[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="first",
        bare_calls=True,
    )
)

_register_lang(
    LangSpec(
        name="kotlin",
        extensions=(".kt", ".kts"),
        aliases=("kt",),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r'"""[\s\S]*?"""', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "fun", "val", "var", "class", "interface", "object", "enum",
                "data", "sealed", "abstract", "open", "override", "internal",
                "public", "private", "protected", "companion", "init",
                "constructor", "import", "package", "if", "else", "when",
                "for", "while", "do", "return", "break", "continue", "try",
                "catch", "finally", "throw", "this", "super", "null", "true",
                "false", "by", "as", "is", "in", "out", "reified", "inline",
                "noinline", "crossinline", "suspend", "operator", "infix",
                "tailrec", "lateinit", "lazy", "List", "MutableList", "Map",
                "Set", "String", "Int", "Double", "Boolean", "Long", "Array",
                "Any", "Unit", "Nothing", "println", "print", "listOf",
                "mapOf", "setOf", "mutableListOf", "mutableMapOf",
            }
        ),
        defn_patterns=(
            r"\bfun\s+(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)\s*\(",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\binterface\s+([A-Za-z_]\w*)",
            r"\benum\s+(?:class\s+)?([A-Za-z_]\w*)",
            r"\bobject\s+([A-Za-z_]\w*)",
            r"\bval\s+([A-Za-z_]\w*)\s*[:=]",
            r"\bvar\s+([A-Za-z_]\w*)\s*[:=]",
            r"\bconst\s+val\s+([A-Za-z_]\w*)",
        ),
        import_patterns=(r"\bimport\s+(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)",),
        param_patterns=(r"\bfun\s+(?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="before_colon",
    )
)

_register_lang(
    LangSpec(
        name="swift",
        extensions=(".swift",),
        aliases=(),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r'"""[\s\S]*?"""'),
        keywords=frozenset(
            {
                "func", "class", "struct", "enum", "protocol", "extension",
                "let", "var", "import", "return", "if", "else", "guard",
                "for", "while", "repeat", "switch", "case", "default",
                "break", "continue", "try", "catch", "throw", "throws", "do",
                "in", "as", "is", "nil", "true", "false", "self", "super",
                "init", "deinit", "public", "private", "internal",
                "fileprivate", "open", "static", "final", "override", "lazy",
                "weak", "unowned", "where", "String", "Int", "Double",
                "Bool", "Array", "Dictionary", "Set", "Optional", "print",
                "count", "map", "filter", "reduce", "sorted", "first",
                "last", "isEmpty",
            }
        ),
        defn_patterns=(
            r"\bfunc\s+([A-Za-z_]\w*)\s*\(",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\bstruct\s+([A-Za-z_]\w*)",
            r"\benum\s+([A-Za-z_]\w*)",
            r"\bprotocol\s+([A-Za-z_]\w*)",
            r"\bextension\s+([A-Za-z_]\w*)",
            r"\blet\s+([A-Za-z_]\w*)\s*[:=]",
            r"\bvar\s+([A-Za-z_]\w*)\s*[:=]",
            r"\bstatic\s+let\s+([A-Za-z_]\w*)",
        ),
        import_patterns=(r"\bimport\s+(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)",),
        param_patterns=(r"\bfunc\s+[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="before_colon",
    )
)

_register_lang(
    LangSpec(
        name="dart",
        extensions=(".dart",),
        aliases=(),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "class", "void", "int", "double", "bool", "String", "List",
                "Map", "Set", "dynamic", "final", "const", "var", "if",
                "else", "for", "while", "do", "switch", "case", "default",
                "break", "continue", "return", "new", "this", "super",
                "extends", "implements", "with", "mixin", "abstract",
                "static", "get", "set", "import", "export", "library",
                "part", "async", "await", "yield", "null", "true", "false",
                "throw", "try", "catch", "finally", "rethrow", "assert",
                "in", "is", "as", "factory", "covariant", "typedef",
                "deferred", "required", "late", "print", "main",
            }
        ),
        defn_patterns=(
            r"\b(?:void|int|double|bool|String|List|Map|Set|dynamic|[A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(",
            r"\bclass\s+([A-Za-z_]\w*)",
            r"\bmixin\s+([A-Za-z_]\w*)",
            r"\benum\s+([A-Za-z_]\w*)",
            r"\b(?:final|const|var|late)\s+([A-Za-z_]\w*)\s*[:=]",
        ),
        import_patterns=(),
        param_patterns=(
            r"\b(?:void|int|double|bool|String|List|Map|Set|dynamic|[A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*\(([^)]*)\)",
        ),
        param_mode="last",
    )
)

_register_lang(
    LangSpec(
        name="lua",
        extensions=(".lua",),
        aliases=(),
        line_comments=("--",),
        block_comments=(("--[[", "]]"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "function", "local", "if", "then", "else", "elseif", "end",
                "for", "while", "repeat", "until", "do", "return", "break",
                "in", "nil", "true", "false", "and", "or", "not", "goto",
                "require", "self", "pcall", "xpcall", "pairs", "ipairs",
                "print", "tonumber", "tostring", "type", "error", "assert",
                "select", "unpack", "string", "table", "math", "os", "io",
            }
        ),
        defn_patterns=(
            r"\bfunction\s+(?:[A-Za-z_]\w*[.:])*([A-Za-z_]\w*)\s*\(",
            r"\blocal\s+([A-Za-z_]\w*)\s*(?:=|,|$)",
            r"\b([A-Za-z_]\w*)\s*=\s*function\s*\(",
        ),
        import_patterns=(),
        param_patterns=(r"\bfunction\s+(?:[A-Za-z_]\w*[.:])*[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="first",
    )
)

_register_lang(
    LangSpec(
        name="r",
        extensions=(".r",),
        aliases=("rlang",),
        line_comments=("#",),
        block_comments=(),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "function", "if", "else", "for", "while", "repeat", "break",
                "next", "return", "in", "TRUE", "FALSE", "NULL", "NA",
                "NaN", "Inf", "library", "require", "source", "install.packages",
                "c", "list", "data.frame", "print", "cat", "sum", "mean",
                "length", "nrow", "ncol", "str", "head", "tail", "names",
                "lapply", "sapply", "apply", "tapply", "mapply", "aggregate",
                "subset", "transform", "merge", "rbind", "cbind", "seq",
                "rep", "paste", "paste0", "sprintf", "grep", "sub", "gsub",
                "match", "which", "unique", "sort", "order", "table",
                "summary", "plot", "hist", "boxplot", "lm", "glm", "t.test",
                "chisq.test", "read.csv", "read.table", "write.csv",
                "setwd", "getwd",
            }
        ),
        defn_patterns=(
            r"([A-Za-z_]\w*)\s*(?:<-|=)\s*function\s*\(",
            r"([A-Za-z_]\w*)\s*<-\s*",
        ),
        import_patterns=(r"\b(?:library|require)\s*\(\s*['\"]?([A-Za-z0-9.]+)['\"]?\s*\)",),
        param_patterns=(r"\bfunction\s*\(([^)]*)\)",),
        param_mode="first",
    )
)

_register_lang(
    LangSpec(
        name="zig",
        extensions=(".zig",),
        aliases=(),
        line_comments=("//",),
        block_comments=(("/*", "*/"),),
        strings=(r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"),
        keywords=frozenset(
            {
                "fn", "const", "var", "if", "else", "for", "while", "switch",
                "case", "return", "break", "continue", "pub", "comptime",
                "defer", "errdefer", "try", "catch", "unreachable", "null",
                "true", "false", "undefined", "struct", "enum", "union",
                "error", "type", "anytype", "void", "bool", "u8", "u16",
                "u32", "u64", "u128", "usize", "i8", "i16", "i32", "i64",
                "i128", "isize", "f32", "f64", "and", "or", "not",
                "andalso", "orelse", "std",
            }
        ),
        defn_patterns=(
            r"\bfn\s+([A-Za-z_]\w*)\s*\(",
            r"\b(?:pub\s+)?const\s+([A-Za-z_]\w*)\s*=",
            r"\b(?:pub\s+)?var\s+([A-Za-z_]\w*)\s*=",
        ),
        import_patterns=(r"\bconst\s+[A-Za-z_]\w*\s*=\s*@import\s*\(\s*\"([A-Za-z0-9_.]+)\"",),
        param_patterns=(r"\bfn\s+[A-Za-z_]\w*\s*\(([^)]*)\)",),
        param_mode="before_colon",
    )
)

# Public surface for CLI/schema, derived from the two language tables above so
# it cannot drift from what the engine actually dispatches.
def canonical_languages() -> tuple[str, ...]:
    """Every language the verifier can analyze, by canonical name."""
    return tuple(sorted({*_NATIVE_LANGS, *_LANG_REGISTRY}))


def language_aliases() -> tuple[str, ...]:
    """Canonical names plus every accepted alias (what the CLI/schema allow)."""
    names = set(_NATIVE_BY_ALIAS) | set(_LANG_ALIASES)
    return tuple(sorted(names))


def source_extensions() -> tuple[str, ...]:
    """File suffixes belonging to a supported language.

    Used by the CLI to tell a path argument from inline source and by the tree
    walker to decide what is worth reading, so adding a language to the
    registry also makes it visible to `gate`/`scan` in one step.
    """
    exts: set[str] = {e for cfg in _NATIVE_LANGS.values() for e in cfg["extensions"]}
    exts |= {e for spec in _LANG_REGISTRY.values() for e in spec.extensions}
    return tuple(sorted(exts))


def language_for_file(path: str) -> str | None:
    """Canonical language owning a file suffix (``.jsx`` → ``javascript``)."""
    suffix = os.path.splitext(path or "")[1].lower()
    if not suffix:
        return None
    for name, cfg in _NATIVE_LANGS.items():
        if suffix in cfg["extensions"]:
            return name
    for spec in _LANG_REGISTRY.values():
        if suffix in spec.extensions:
            return spec.name
    return None


# Import-time guard: a registry entry without suffixes is silently invisible to
# the CLI's path heuristic and to tree scanning, which is exactly the class of
# drift this table-based design removes.
_UNDECLARED = tuple(
    sorted(n for n, spec in _LANG_REGISTRY.items() if not spec.extensions)
)
if _UNDECLARED:  # pragma: no cover - a development-time invariant, not a runtime path
    raise RuntimeError(
        "language registry entries missing file extensions: " + ", ".join(_UNDECLARED)
    )

SUPPORTED_LANGUAGES: tuple[str, ...] = language_aliases()


# Match-statement node types exist only on Python 3.10+; resolve once so
# older interpreters skip these branches instead of raising AttributeError.
_MATCH_AS = getattr(ast, "MatchAs", None)
_MATCH_STAR = getattr(ast, "MatchStar", None)
_MATCH_MAPPING = getattr(ast, "MatchMapping", None)


def _python_defined_symbols(tree: ast.AST) -> set[str]:
    """Names defined or imported by a parsed Python module (for ``defined_symbols``)."""
    defined: set[str] = set(dir(builtins))
    defined |= {
        "__file__",
        "__doc__",
        "__package__",
        "__spec__",
        "__loader__",
        "__main__",
        "__dict__",
        "__builtins__",
        "__cached__",
    }
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            defined.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif _MATCH_AS is not None and isinstance(node, _MATCH_AS) and node.name:
            defined.add(node.name)  # case pattern capture, py3.10+
        elif _MATCH_STAR is not None and isinstance(node, _MATCH_STAR) and node.name:
            defined.add(node.name)
        elif _MATCH_MAPPING is not None and isinstance(node, _MATCH_MAPPING) and node.rest:
            defined.add(node.rest)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)

    defined |= imported
    return defined


def defined_symbols(source: str, language: str = "python") -> list[str]:
    """Names the source defines or imports (sorted). Used by ``check_contract``
    to verify that ``requires`` symbols actually exist in the module.

    Same language support as ``detect_undefined_symbols``: Python (AST),
    TypeScript/JavaScript (lexical), and the config-driven generic registry.
    Returns [] for unsupported languages or unparseable Python.
    """
    lang = (language or "python").strip().lower()
    if lang in ("typescript", "ts", "javascript", "js"):
        return sorted(_ts_defined_symbols(source))
    spec = resolve_language(lang)
    if spec is not None:
        return sorted(_generic_defined(_mask_source(source, spec), spec))
    if lang == "python":
        try:
            return sorted(_python_defined_symbols(ast.parse(source)))
        except SyntaxError:
            return []
    return []


def detect_undefined_symbols(
    source: str, language: str = "python", suppress: list[str] | None = None
) -> dict:
    """Parse source and return symbols that look hallucinated
    (used/called but never defined or imported).

    Supported languages come from two tables and are enumerated by
    ``canonical_languages()``: the natively-analyzed ones (Python via AST,
    TypeScript/JavaScript via a lexical pass) and the config-driven generic
    lexical registry. Adding a language is a table entry, never an edit to
    this function.
    ``suppress`` removes exact symbol names from the findings (config:
    ``suppress_symbols``); suppressed names are reported separately so the
    omission stays visible.

    Returns:
        {"language": ..., "suspects": ["foo", "Bar"],
         "suspects_detail": [{"name": "foo", "line": 12}, ...],
         "suppressed": ["bar"], "note": "..."}
    """
    native = native_language(language)
    if native is not None and native[1] == "ts_lexical":
        suspects, note = _detect_ts_undefined(source)
        return _apply_suppress({"language": language, "suspects": suspects, "note": note}, suppress)
    if native is None:
        spec = resolve_language(language)
        if spec is not None:
            suspects, note = _generic_detect_undefined(source, spec)
            return _apply_suppress(
                {"language": spec.name, "suspects": suspects, "note": note}, suppress
            )
        return {
            "language": language,
            "suspects": [],
            "note": "Unsupported language. Supported: " + ", ".join(SUPPORTED_LANGUAGES) + ".",
        }

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "language": "python",
            "suspects": [],
            "note": f"Cannot parse (syntax error): {exc}",
        }

    defined = _python_defined_symbols(tree)

    # flake8-convention suppression: a trailing `# noqa` (bare or with codes,
    # case-insensitive — django ships `# NOQA: F821` on forward-referencing
    # annotations) marks the line as knowingly-unresolved. Skipping those
    # lines keeps real projects clean without weakening unmarked lines.
    noqa_lines = {
        i
        for i, line in enumerate(source.splitlines(), 1)
        if re.search(r"#\s*noqa\b", line, re.IGNORECASE)
    }

    # `from x import *` makes every module-level name potentially defined, so
    # a single-file scope walk would flag most real code as hallucinated. An
    # honest empty result beats an unreliable one; pyflakes does not help here
    # either, because its star-import findings are a different message class
    # than UndefinedName and never reach the merge below.
    if any(
        isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names)
        for node in ast.walk(tree)
    ):
        return {
            "language": "python",
            "suspects": [],
            "note": "Wildcard import (from x import *) present: single-file scope "
            "analysis cannot resolve star-imported names, so undefined-name "
            "detection is disabled for this module. Use verify_file with a "
            "toolchain verifier (ruff/pyflakes) for star-import-aware analysis.",
        }

    seen: set[str] = set()
    suspects: list[str] = []
    detail: list[dict] = []
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
        elif isinstance(node, ast.Delete):
            # `del x` on a never-defined name raises NameError at runtime;
            # the Load/Call contexts above never visit Del targets, so this
            # class needs its own check (works without pyflakes too).
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id not in defined
                    and target.id not in seen
                ):
                    seen.add(target.id)
                    suspects.append(target.id)
                    detail.append({"name": target.id, "line": getattr(target, "lineno", 0)})
        if name is not None and name not in defined and name not in seen:
            lineno = getattr(node, "lineno", 0)
            if re.fullmatch(r"__\w+__", name):
                # interpreter protocol names (__path__, __version__, __all__):
                # resolved by the import machinery, never by scope analysis
                continue
            if lineno in noqa_lines:
                continue  # knowingly-unresolved per the flake8 convention
            seen.add(name)
            suspects.append(name)
            detail.append({"name": name, "line": lineno})

    pyfindings = _pyflakes_undefined(source)
    note = (
        "Static scope analysis only; no runtime; attribute calls "
        "(foo.bar) are not expanded and may cause false negatives. "
        "Dunder protocol names and `# noqa`-marked lines are not flagged."
    )
    if pyfindings is not None:
        for name, line in pyfindings:
            if name in defined or name in seen or line in noqa_lines:
                continue
            if re.fullmatch(r"__\w+__", name):
                continue  # dunder protocol names: same skip as the AST pass
            seen.add(name)
            suspects.append(name)
            detail.append({"name": name, "line": line})
        note += " Merged with pyflakes F821 scope analysis."

    # did-you-mean: the closest real names, so a flagged symbol turns into a
    # 2-second fix instead of a dead end (candidates include builtins).
    for d in detail:
        d["suggestions"] = difflib.get_close_matches(d["name"], defined, n=3, cutoff=0.6)

    return _apply_suppress(
        {
            "language": "python",
            "suspects": suspects,
            "suspects_detail": detail,
            "note": note,
        },
        suppress,
    )


def _apply_suppress(result: dict, suppress: list[str] | None) -> dict:
    """Filter suppressed symbol names out of a detection result (visible)."""
    if not suppress:
        result.setdefault("suppressed", [])
        return result
    drop = {s for s in suppress if isinstance(s, str)}
    kept = [s for s in result["suspects"] if s not in drop]
    removed = [s for s in result["suspects"] if s in drop]
    out = dict(result)
    out["suspects"] = kept
    out["suppressed"] = removed
    if "suspects_detail" in out:
        out["suspects_detail"] = [d for d in out["suspects_detail"] if d["name"] not in drop]
    return out
