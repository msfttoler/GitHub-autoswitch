"""Configuration loading and validation for ghx."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

CONFIG_DEFAULT_PATH = Path("~/.config/ghx/config.yml").expanduser()

EXAMPLE_CONFIG = """\
# ghx configuration
# See: https://github.com/msfttoler/GitHub-autoswitch

accounts:
  work: your-work-login
  personal: your-personal-login
  # oss: your-oss-login

# Per-host defaults (supports GitHub Enterprise)
hosts:
  github.com:
    default_account: personal
  # github.mycompany.com:
  #   default_account: work

rules:
  # Directory-based rules (first match wins)
  - path: "~/code/work/**"
    account: work
  - path: "~/code/personal/**"
    account: personal

  # Git remote org/owner rules
  # - remote_org: my-company
  #   account: work
  #   host: github.mycompany.com   # optional, defaults to github.com

default_account: personal

behavior:
  on_switch_error: warn-and-continue  # or: fail
  on_undetermined: prompt              # or: fallback-default, skip
"""


@dataclass
class BehaviorConfig:
    on_switch_error: str = "warn-and-continue"  # warn-and-continue | fail
    on_undetermined: str = "prompt"  # prompt | fallback-default | skip


@dataclass
class Rule:
    path: str | None = None
    remote_org: str | None = None
    account: str = ""
    host: str | None = None


@dataclass
class HostConfig:
    default_account: str | None = None


@dataclass
class GhxConfig:
    accounts: dict[str, str] = field(default_factory=dict)
    hosts: dict[str, HostConfig] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    default_account: str | None = None
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)

    def resolve_label(
        self, label_or_login: str, known_logins: list[str] | None = None
    ) -> str | None:
        """Resolve an account label or login to the actual login name."""
        # Label → login mapping
        if label_or_login in self.accounts:
            return self.accounts[label_or_login]
        # Direct login match among known logins
        if known_logins and label_or_login in known_logins:
            return label_or_login
        # Direct login match against configured values
        if label_or_login in self.accounts.values():
            return label_or_login
        return None

    def get_host_default(self, host: str) -> str | None:
        """Get the default account label for a specific host."""
        host_cfg = self.hosts.get(host)
        if host_cfg and host_cfg.default_account:
            return host_cfg.default_account
        return self.default_account


def load_config(path: Path | None = None) -> GhxConfig:
    """Load and parse the ghx configuration file."""
    config_path = path or CONFIG_DEFAULT_PATH

    if not config_path.exists():
        return GhxConfig()

    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read config files. Install with: pip install pyyaml"
        )

    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        return GhxConfig()

    return _parse_raw_config(raw)


def _parse_raw_config(raw: dict[str, Any]) -> GhxConfig:
    """Parse raw YAML dict into a typed GhxConfig."""
    accounts = raw.get("accounts") or {}
    if not isinstance(accounts, dict):
        accounts = {}

    hosts: dict[str, HostConfig] = {}
    for host_name, host_data in (raw.get("hosts") or {}).items():
        if isinstance(host_data, dict):
            hosts[host_name] = HostConfig(
                default_account=host_data.get("default_account")
            )

    rules: list[Rule] = []
    for rule_data in raw.get("rules") or []:
        if isinstance(rule_data, dict):
            rules.append(
                Rule(
                    path=rule_data.get("path"),
                    remote_org=rule_data.get("remote_org"),
                    account=rule_data.get("account", ""),
                    host=rule_data.get("host"),
                )
            )

    behavior_raw = raw.get("behavior") or {}
    behavior = BehaviorConfig(
        on_switch_error=behavior_raw.get("on_switch_error", "warn-and-continue"),
        on_undetermined=behavior_raw.get("on_undetermined", "prompt"),
    )

    return GhxConfig(
        accounts=accounts,
        hosts=hosts,
        rules=rules,
        default_account=raw.get("default_account"),
        behavior=behavior,
    )


def ensure_config_dir(path: Path | None = None) -> Path:
    """Ensure the config directory exists and return the config file path."""
    config_path = path or CONFIG_DEFAULT_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    return config_path


def write_example_config(path: Path | None = None) -> Path:
    """Write the example config to disk."""
    config_path = ensure_config_dir(path)
    config_path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    return config_path
