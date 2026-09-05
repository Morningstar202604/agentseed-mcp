"""AgentSeed guard engine — modular package.

Modules:
  config    — Config loading (load_config, config helpers)
  symbols   — Undefined symbol detection (detect_undefined_symbols)
  hallucination — Hallucination word scanning (scan_hallucination_words)
  verifiers — Toolchain verifier adapters (run_verifier, list_verifiers)
  plugin    — Agent Plugins 1.0.0 conformance checker (check_plugin_conformance)
  sandbox   — Deterministic execution channel (sandbox_run)
  schema    — JSON Schema subset validator (schema_validate)
  audit     — Verification audit trail (record_verification)
  receipt   — Evidence receipts (build_receipt)
  artifact  — Generic plugin packer (pack_plugin)

Public API only: internal helpers stay inside their modules.
"""

from .artifact import pack_plugin
from .audit import (
    VALID_STATUSES,
    audit_path,
    changed_files,
    coverage,
    record_verification,
    verified_files,
)
from .config import (
    CONFIG_FILENAME,
    KNOWN_CONFIG_KEYS,
    SANDBOX_ENV_MODES,
    VALID_GROUPS,
    config_bool,
    config_extra_tokens,
    config_severities,
    config_str_list,
    load_config,
    parse_timeout,
    sandbox_env_mode,
    unknown_config_keys,
)
from .hallucination import (
    DEFAULT_ALLOWLIST,
    DEFAULT_SEVERITIES,
    HALLUCINATION_WORDS,
    merge_allowlist,
    scan_hallucination_words,
)
from .imports import check_imports, check_manifest, manifest_kind_for_path, manifest_names
from .index import (
    build_index,
    find_project_root,
    resolve_symbols,
    symbol_map,
    verify_in_project,
)
from .plugin import check_plugin_conformance
from .receipt import build_receipt
from .sandbox import build_env, kill_tree, resolve_executable, sandbox_run
from .schema import schema_validate
from .symbols import defined_symbols, detect_undefined_symbols
from .verifiers import list_verifiers, run_verifier
from .version import plugin_version

__all__ = [
    "CONFIG_FILENAME",
    "DEFAULT_ALLOWLIST",
    "DEFAULT_SEVERITIES",
    "HALLUCINATION_WORDS",
    "KNOWN_CONFIG_KEYS",
    "SANDBOX_ENV_MODES",
    "VALID_GROUPS",
    "VALID_STATUSES",
    "audit_path",
    "build_env",
    "build_index",
    "build_receipt",
    "changed_files",
    "check_plugin_conformance",
    "check_imports",
    "check_manifest",
    "config_bool",
    "config_extra_tokens",
    "config_severities",
    "config_str_list",
    "coverage",
    "detect_undefined_symbols",
    "defined_symbols",
    "find_project_root",
    "kill_tree",
    "list_verifiers",
    "load_config",
    "manifest_kind_for_path",
    "manifest_names",
    "merge_allowlist",
    "pack_plugin",
    "parse_timeout",
    "plugin_version",
    "record_verification",
    "resolve_executable",
    "resolve_symbols",
    "run_verifier",
    "sandbox_env_mode",
    "sandbox_run",
    "scan_hallucination_words",
    "schema_validate",
    "symbol_map",
    "unknown_config_keys",
    "verified_files",
    "verify_in_project",
]
