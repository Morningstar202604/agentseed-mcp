"""AgentSeed hallucination word scanning.

Flags tokens across four signal groups:
  - stub_code:      stub/mock/fake/placeholder/dummy/todo/...
  - oversold:       guaranteed/"all tests pass"/"production ready"/...
  - fabricated:     simulated/invented/fabricated/...
  - fabricated_url: placeholder or reserved-TLD domains (phantom squatting)
"""

from __future__ import annotations

import re

from .config import _VALID_SEVERITIES

# ---------------------------------------------------------------------------
# Hallucination token pools (grouped by signal type).
# ---------------------------------------------------------------------------

STUB_TOKENS = [
    "stub",
    "mock",
    "fake",
    "placeholder",
    "dummy",
    "todo",
    "fixme",
    "xxx",
    "tbd",
    "tba",
    "wip",
    "not implemented",
    "coming soon",
    "to be implemented",
    "not implemented yet",
    "pending implementation",
]

# CJK tokens: \b word boundaries are meaningless between CJK chars, so these
# are matched as substrings (they are specific enough to stay low-noise).
STUB_TOKENS_ZH = [
    "占位",
    "待实现",
    "未实现",
    "待补充",
    "稍后补",
    "假数据",
    "模拟数据",
    "临时方案",
    "先这样",
    "待完成",
    "尚未实现",
]

OVERSOLD_TOKENS = [
    "guaranteed",
    "definitely works",
    "all tests pass",
    "everything works",
    "fully tested",
    "production ready",
    "no bugs",
    "works perfectly",
    "should work",
    "trust me",
    "works on my machine",
    "100% correct",
    "bug free",
    "zero errors",
    "foolproof",
    "bulletproof",
    "cannot fail",
    "guaranteed to pass",
    "impossible to break",
    # security claims (unverified)
    "no vulnerabilities",
    "vulnerability free",
    "secure by design",
    "unhackable",
    # performance claims (unverified)
    "highly optimized",
    "zero downtime",
    "infinitely scalable",
]

OVERSOLD_TOKENS_ZH = [
    "保证通过",
    "绝对没问题",
    "肯定能跑",
    "万无一失",
    "完美运行",
    "零缺陷",
    "无需测试",
    "包过",
    "绝无问题",
    "不可能失败",
    "绝对可靠",
    "稳过",
    "绝对安全",
    "毫无漏洞",
    "零漏洞",
    "永不停机",
    "超高性能",
    "安全无虞",
]

FABRICATED_TOKENS = [
    "simulated",
    "invented",
    "fabricated",
    "fictional",
    "pretend",
    "made up",
    "fictitious",
    "nonexistent",
    "non-existent",
    "mythical",
]

FABRICATED_TOKENS_ZH = [
    "虚构",
    "编造",
    "凭空捏造",
    "子虚乌有",
]

# Placeholder domains are caught by the structural domain rules below
# (_DOMAIN_RE + _is_fabricated_url), not by literal tokens; the EN literal
# pool stays empty so config-driven extension keeps one uniform shape.
FABRICATED_URL_TOKENS: list[str] = []

FABRICATED_URL_TOKENS_ZH = [
    "你的域名",
    "示例域名",
]

# Full pool: token -> group (kept for backward compatibility).
HALLUCINATION_WORDS: dict[str, str] = {}
for _tokens, _group in [
    (STUB_TOKENS + STUB_TOKENS_ZH, "stub_code"),
    (OVERSOLD_TOKENS + OVERSOLD_TOKENS_ZH, "oversold"),
    (FABRICATED_TOKENS + FABRICATED_TOKENS_ZH, "fabricated"),
    (FABRICATED_URL_TOKENS + FABRICATED_URL_TOKENS_ZH, "fabricated_url"),
]:
    for _t in _tokens:
        HALLUCINATION_WORDS[_t] = _group

_GROUP_LABELS = {
    "stub_code": "placeholder / not-really-done code",
    "oversold": "unverified confidence claim",
    "fabricated": "fabricated / invented content",
    "fabricated_url": "placeholder / reserved-TLD domain (phantom squatting)",
}

# Tokens that are legitimate in common testing/idiomatic contexts.
DEFAULT_ALLOWLIST = [
    "unittest.mock",
    "Mock(",
    "MagicMock(",
    "AsyncMock(",
    "PropertyMock(",
    "patch(",
    "monkeypatch",
    "mocker",
]

_IMPORT_LINE_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\b|import\s+\w)", re.IGNORECASE)

# Default severity per signal group.
DEFAULT_SEVERITIES: dict[str, str] = {
    "stub_code": "warning",
    "oversold": "error",
    "fabricated": "error",
    "fabricated_url": "warning",
}

# ---------------------------------------------------------------------------
# Precompiled regex patterns (one per group, compiled once at import time).
# ASCII tokens use \b word boundaries; CJK tokens are substring matches
# (\b never fires between two CJK chars, so boundaries would miss 占位符 etc).
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _compile_group(tokens: list[str]) -> re.Pattern:
    ascii_alts = [re.escape(t).replace(r"\ ", r"\s+") for t in tokens if not _CJK_RE.search(t)]
    cjk_alts = [re.escape(t) for t in tokens if _CJK_RE.search(t)]
    parts = []
    if ascii_alts:
        parts.append(rf"\b(?:{'|'.join(ascii_alts)})\b")
    if cjk_alts:
        parts.append("|".join(cjk_alts))
    return re.compile("(?:" + "|".join(parts) + ")", re.IGNORECASE)


_HALLUCINATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (_compile_group(STUB_TOKENS + STUB_TOKENS_ZH), "stub_code"),
    (_compile_group(OVERSOLD_TOKENS + OVERSOLD_TOKENS_ZH), "oversold"),
    (_compile_group(FABRICATED_TOKENS + FABRICATED_TOKENS_ZH), "fabricated"),
    (_compile_group(FABRICATED_URL_TOKENS + FABRICATED_URL_TOKENS_ZH), "fabricated_url"),
]

# ---------------------------------------------------------------------------
# Fabricated-domain detection (fabricated_url group).
#
# Lexical only, no network: a domain is flagged when it is a placeholder
# stand-in ("api.yourdomain.com"), sits on an RFC/IANA-reserved TLD used as
# if it were real ("myapp.test"), or fabricates the word "example" into a
# domain that is NOT the reserved example.com/net/org/edu set
# ("docs.example-fake-api.dev" — Unit 42's phantom squatting). Real domains
# (github.com, docs.python.org) never match; the allowlist still applies.
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}",
    re.IGNORECASE,
)

# example.com/net/org (RFC 2606) and example.edu (IANA) are THE placeholder
# convention — their exact domains and subdomains stay clean.
_RESERVED_EXAMPLE_SUFFIXES = (".example.com", ".example.net", ".example.org", ".example.edu")

_URL_PLACEHOLDER_MARKERS = (
    "yourdomain",
    "your-domain",
    "yoursite",
    "yourwebsite",
    "yourapi",
    "your-api",
    "mydomain",
    "mysite",
    "mywebsite",
    "fakedomain",
    "fake-domain",
    "testdomain",
    "test-domain",
    "sampledomain",
    "sample-domain",
    "dummydomain",
    "dummy-domain",
    "placeholder-domain",
)

_RESERVED_TLDS = {"test", "invalid", "localhost", "example"}


def _is_fabricated_url(domain: str) -> bool:
    host = domain.lower().rstrip(".")
    if host.endswith(_RESERVED_EXAMPLE_SUFFIXES) or host in (
        "example.com",
        "example.net",
        "example.org",
        "example.edu",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
    ):
        return False
    tld = host.rsplit(".", 1)[-1]
    if tld in _RESERVED_TLDS:
        return True
    if "example" in host:
        return True
    return any(marker in host for marker in _URL_PLACEHOLDER_MARKERS)


def merge_allowlist(base: list[str] | None, extra: list[str] | None) -> list[str] | None:
    """Effective scan exclusions: (config allowlist or the built-in defaults)
    plus ``extra_allowlist`` entries merged AFTER them. ``allow`` writes into
    extra_allowlist, so excluding one word never silently drops the built-in
    test-idiom defaults the way replacing ``allowlist`` would."""
    if base is None and not extra:
        return None
    effective = list(base if base is not None else DEFAULT_ALLOWLIST)
    if extra:
        for item in extra:
            if isinstance(item, str) and item and item not in effective:
                effective.append(item)
    return effective


def scan_hallucination_words(
    source: str,
    allowlist: list[str] | None = None,
    severities: dict[str, str] | None = None,
    extra_tokens: dict[str, list[str]] | None = None,
) -> dict:
    """Scan source for tokens in the grouped hallucination pool.

    To avoid flagging legitimate code, matches are skipped when:
      - the line is an import statement;
      - the match is part of a dotted path (``unittest.mock``, ``os.path``);
      - the matched text starts with an entry of the effective allowlist.

    Beyond the literal token pool, every non-import line also goes through a
    fabricated-domain pass (group ``fabricated_url``): placeholder stand-ins,
    reserved TLDs used as if real, and "example" fabricated into
    non-reserved domains (phantom squatting). The reserved example.com/net/
    org/edu set and the allowlist stay clean.

    ``extra_tokens`` extends the pool at runtime (config: ``extra_tokens``
    mapping group -> [words]); unknown groups are ignored.

    Each hit carries a severity (``error`` | ``warning`` | ``info``) taken
    from ``severities`` (group -> severity), falling back to
    DEFAULT_SEVERITIES.

    Returns:
        {
          "hits": [{"word": "stub", "group": "stub_code", "line": 12,
                    "severity": "warning"}, ...],
          "clean": bool,
          "blocking": bool,
          "groups": {"stub_code": 2, "oversold": 1, "fabricated": 0,
                     "fabricated_url": 0},
          "severities": {"error": 1, "warning": 2, "info": 0}
        }
    """
    if allowlist is None:
        allowlist = DEFAULT_ALLOWLIST
    elif isinstance(allowlist, str):
        # MCP clients sometimes send a bare string instead of a list; a raw
        # string would iterate characters and silently suppress every match.
        allowlist = [allowlist]
    elif not isinstance(allowlist, list):
        allowlist = (
            [a for a in allowlist if isinstance(a, str)] if hasattr(allowlist, "__iter__") else []
        )
    allowlist = [a for a in allowlist if isinstance(a, str) and a]
    sev = dict(DEFAULT_SEVERITIES)
    if severities:
        for g, s in severities.items():
            if g in _GROUP_LABELS and s in _VALID_SEVERITIES:
                sev[g] = s
    patterns = list(_HALLUCINATION_PATTERNS)
    if extra_tokens:
        for g, words in extra_tokens.items():
            if g in _GROUP_LABELS and isinstance(words, list):
                words = [w for w in words if isinstance(w, str) and w]
                if words:
                    patterns.append((_compile_group(words), g))
    hits: list[dict] = []
    group_counts: dict[str, int] = {g: 0 for g in _GROUP_LABELS}
    severity_counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for i, line in enumerate(source.splitlines(), start=1):
        if _IMPORT_LINE_RE.match(line):
            continue
        for pattern, group in patterns:
            for m in pattern.finditer(line):
                before = line[max(0, m.start() - 1) : m.start()]
                after = line[m.end() : m.end() + 1]
                if before == "." or after == ".":
                    continue  # part of a dotted path (module/attribute)
                rest = line[m.start() :]
                if any(rest.lower().startswith(a.lower()) for a in allowlist):
                    continue
                word = m.group(0).lower()
                severity = sev.get(group, "warning")
                hits.append({"word": word, "group": group, "line": i, "severity": severity})
                group_counts[group] += 1
                severity_counts[severity] += 1
        for m in _DOMAIN_RE.finditer(line):
            host = m.group(0)
            if not _is_fabricated_url(host):
                continue
            rest = line[m.start() :]
            if any(rest.lower().startswith(a.lower()) for a in allowlist):
                continue
            severity = sev.get("fabricated_url", "warning")
            hits.append(
                {"word": host.lower(), "group": "fabricated_url", "line": i, "severity": severity}
            )
            group_counts["fabricated_url"] += 1
            severity_counts[severity] += 1
    return {
        "hits": hits,
        "clean": len(hits) == 0,
        "blocking": severity_counts["error"] > 0,
        "groups": group_counts,
        "severities": severity_counts,
    }
