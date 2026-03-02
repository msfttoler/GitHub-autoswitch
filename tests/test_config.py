"""Tests for ghx.config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghx.config import (
    GhxConfig,
    BehaviorConfig,
    Rule,
    HostConfig,
    load_config,
    write_example_config,
    _parse_raw_config,
)


class TestGhxConfig:
    def test_resolve_label_by_label(self, sample_config: GhxConfig):
        assert sample_config.resolve_label("work") == "work-login"
        assert sample_config.resolve_label("personal") == "personal-login"
        assert sample_config.resolve_label("oss") == "oss-login"

    def test_resolve_label_by_login(self, sample_config: GhxConfig, known_logins):
        assert sample_config.resolve_label("work-login", known_logins) == "work-login"

    def test_resolve_label_by_value(self, sample_config: GhxConfig):
        # Should match even without known_logins if it's in accounts.values()
        assert sample_config.resolve_label("work-login") == "work-login"

    def test_resolve_label_unknown(self, sample_config: GhxConfig):
        assert sample_config.resolve_label("nonexistent") is None

    def test_get_host_default(self, sample_config: GhxConfig):
        assert sample_config.get_host_default("github.com") == "personal"
        assert sample_config.get_host_default("github.enterprise.com") == "work"

    def test_get_host_default_fallback(self, sample_config: GhxConfig):
        # Unknown host falls back to global default
        assert sample_config.get_host_default("unknown.host") == "personal"


class TestLoadConfig:
    def test_load_missing_file(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.yml")
        assert cfg.accounts == {}
        assert cfg.default_account is None

    def test_load_empty_file(self, tmp_config: Path):
        tmp_config.write_text("", encoding="utf-8")
        cfg = load_config(tmp_config)
        assert cfg.accounts == {}

    def test_load_valid_config(self, tmp_config: Path):
        tmp_config.write_text(
            """
accounts:
  work: alice
  personal: bob

hosts:
  github.com:
    default_account: personal

rules:
  - path: "~/work/**"
    account: work
  - remote_org: acme-corp
    account: work

default_account: personal

behavior:
  on_switch_error: fail
  on_undetermined: fallback-default
""",
            encoding="utf-8",
        )
        cfg = load_config(tmp_config)
        assert cfg.accounts == {"work": "alice", "personal": "bob"}
        assert cfg.default_account == "personal"
        assert cfg.behavior.on_switch_error == "fail"
        assert cfg.behavior.on_undetermined == "fallback-default"
        assert len(cfg.rules) == 2
        assert cfg.rules[0].path == "~/work/**"
        assert cfg.rules[1].remote_org == "acme-corp"
        assert cfg.hosts["github.com"].default_account == "personal"


class TestWriteExampleConfig:
    def test_writes_file(self, tmp_config: Path):
        result = write_example_config(tmp_config)
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "accounts:" in content
        assert "rules:" in content
        assert "behavior:" in content

    def test_creates_parent_dirs(self, tmp_path: Path):
        deep_path = tmp_path / "a" / "b" / "config.yml"
        result = write_example_config(deep_path)
        assert result.exists()


class TestParseRawConfig:
    def test_handles_bad_accounts(self):
        cfg = _parse_raw_config({"accounts": "not-a-dict"})
        assert cfg.accounts == {}

    def test_handles_missing_sections(self):
        cfg = _parse_raw_config({})
        assert cfg.accounts == {}
        assert cfg.rules == []
        assert cfg.behavior.on_switch_error == "warn-and-continue"

    def test_handles_rule_missing_fields(self):
        cfg = _parse_raw_config({"rules": [{"path": "~/foo"}]})
        assert len(cfg.rules) == 1
        assert cfg.rules[0].account == ""
