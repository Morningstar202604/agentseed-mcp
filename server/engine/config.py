"""AgentSeed config loading — zero dependencies."""

from __future__ import annotations

import json
import os

CONFIG_FILENAME = "agentseed.config.json"
_VALID_SEVERITIES = {"error", "warning", "info"}
VALID_GROUPS = {"stub_code", "oversold", "fabricated", "fabricated_url"}

# Every key load_config() understands; anything else is a likely typo and
# callers should surface a warning (silently ignoring typos = silent no-op).
KNOWN_CONFIG_KEYS = {
    "allowlist",
    "extra_allowlist",
    "severities",
    "timeout",
    "extra_tokens",
    "suppress_symbols",
    "sandbox_allowed_prefixes",
    "sandbox_env",
    "known_packages",
    "hook_profile",
    "project_index",
}

SANDBOX_ENV_MODES = ("inherit", "scrub")


def sandbox_env_mode(config: dict, default: str = "inherit") -> str:
    """Validated sandbox_env mode from config ("inherit" | "scrub")."""
    value = config.get("sandbox_env", default)
    return value if value in SANDBOX_ENV_MODES else default


def load_config(explicit_path: str | None = None) -> dict:
    """Load the effective AgentSeed config (zero dependencies).

    Search order (first hit wins):
      1. ``explicit_path`` argument
      2. ``AGENTSEED_CONFIG`` environment variable
      3. ``${PLUGIN_DATA}/agentseed.config.json``
      4. ``./agentseed.config.json`` in the current working directory.

    Recognized keys (all optional):
      allowlist                : list[str] - scan exclusions (replaces DEFAULT_ALLOWLIST)
      severities               : dict[str, str] - group -> error|warning|info
      timeout                  : int - default sandbox_run timeout in seconds
      extra_tokens             : dict[group, list[str]] - extra hallucination words
      suppress_symbols         : list[str] - names verify_code never flags
      known_packages           : list[str] - packages check_imports treats as known
                                    (project-local / trusted third-party), beyond stdlib
      sandbox_allowed_prefixes : list[str] - executable allowlist for sandbox_run
                                                 (absent/empty = unrestricted)
      hook_profile             : str - guard_hook gate profile: advisory (default,
                                       report only) | diff (block only new signals
                                       vs the file's previous content) | strict
                                       (block on any error-severity finding)
      extra_allowlist          : list[str] - scan exclusions MERGED AFTER the built-in
                                       test-idiom defaults ("allow" writes here, so
                                       allowing one word never drops the defaults)
      project_index            : bool - cross-file symbol index for the built-in
                                       analyzer (default true; false = single-file
                                       scope only)

    Returns {} when no config file exists or it cannot be parsed.
    """
    candidates: list[str] = []
    if explicit_path:
        candidates.append(explicit_path)
    env_path = os.environ.get("AGENTSEED_CONFIG")
    if env_path:
        candidates.append(env_path)
    plugin_data = os.environ.get("PLUGIN_DATA")
    if plugin_data:
        candidates.append(os.path.join(plugin_data, CONFIG_FILENAME))
    candidates.append(CONFIG_FILENAME)

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError):
                continue
    return {}


def config_str_list(config: dict, key: str) -> list[str] | None:
    """Extract a validated string-list value from config, or None."""
    value = config.get(key)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def config_severities(config: dict) -> dict[str, str] | None:
    """Extract a validated severities map from config, or None."""
    value = config.get("severities")
    if isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) and v in _VALID_SEVERITIES
        for k, v in value.items()
    ):
        return value
    return None


def config_bool(config: dict, key: str, default: bool = True) -> bool:
    """Extract a validated boolean from config, or the default."""
    value = config.get(key, default)
    return value if isinstance(value, bool) else default


def parse_timeout(config: dict, default: int = 30) -> int:
    """Extract and validate timeout from config dict."""
    try:
        return int(config.get("timeout", default))
    except (TypeError, ValueError):
        return default


def unknown_config_keys(config: dict) -> list[str]:
    """Keys present in ``config`` that load_config() does not understand.

    A typo'd key is silently ignored by every consumer — surfacing it turns
    a silent no-op into an actionable warning.
    """
    if not isinstance(config, dict):
        return []
    return sorted(k for k in config if k not in KNOWN_CONFIG_KEYS)


def config_extra_tokens(config: dict) -> dict[str, list[str]] | None:
    """Validate the extra_tokens mapping {group: [words]}, or None."""
    value = config.get("extra_tokens")
    if not isinstance(value, dict):
        return None
    out: dict[str, list[str]] = {}
    for group, words in value.items():
        if (
            group in VALID_GROUPS
            and isinstance(words, list)
            and all(isinstance(w, str) and w for w in words)
            and words
        ):
            out[group] = words
    return out or None
