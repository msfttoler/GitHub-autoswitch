"""Tests for ghx.inference module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ghx.config import GhxConfig, Rule, HostConfig
from ghx.inference import (
    infer_account,
    _find_repo_root,
    _parse_remote_url,
    _check_repo_override,
    _check_dir_rules,
    _check_ecosystem_files,
)


class TestFindRepoRoot:
    def test_finds_git_dir(self, tmp_repo: Path):
        sub = tmp_repo / "src" / "deep"
        sub.mkdir(parents=True)
        assert _find_repo_root(sub) == tmp_repo

    def test_returns_none_without_git(self, tmp_path: Path):
        assert _find_repo_root(tmp_path) is None


class TestParseRemoteUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            (
                "https://github.com/org/repo.git",
                ("github.com", "org", "repo"),
            ),
            (
                "https://github.com/org/repo",
                ("github.com", "org", "repo"),
            ),
            (
                "git@github.com:org/repo.git",
                ("github.com", "org", "repo"),
            ),
            (
                "git@github.enterprise.com:my-company/service.git",
                ("github.enterprise.com", "my-company", "service"),
            ),
            (
                "ssh://git@github.com/org/repo.git",
                ("github.com", "org", "repo"),
            ),
            (
                "not-a-url",
                (None, None, None),
            ),
        ],
    )
    def test_parse(self, url, expected):
        assert _parse_remote_url(url) == expected


class TestRepoOverride:
    def test_reads_gh_user_file(self, tmp_repo, sample_config, known_logins):
        (tmp_repo / ".gh-user").write_text("work", encoding="utf-8")
        sig = _check_repo_override(tmp_repo, sample_config, known_logins)
        assert sig is not None
        assert sig.source == "repo-override"
        assert sig.account_label == "work"
        assert sig.confidence == 1.0

    def test_no_file_returns_none(self, tmp_repo, sample_config, known_logins):
        sig = _check_repo_override(tmp_repo, sample_config, known_logins)
        assert sig is None

    def test_empty_file_returns_none(self, tmp_repo, sample_config, known_logins):
        (tmp_repo / ".gh-user").write_text("", encoding="utf-8")
        sig = _check_repo_override(tmp_repo, sample_config, known_logins)
        assert sig is None

    def test_unknown_label_returns_none(self, tmp_repo, sample_config, known_logins):
        (tmp_repo / ".gh-user").write_text("nonexistent", encoding="utf-8")
        sig = _check_repo_override(tmp_repo, sample_config, known_logins)
        assert sig is None


class TestDirRules:
    def test_matches_prefix_rule(self, sample_config, known_logins):
        cwd = Path.home() / "code" / "work" / "project-a"
        sig = _check_dir_rules(cwd, sample_config, known_logins)
        assert sig is not None
        assert sig.account_label == "work"
        assert sig.confidence == 0.9

    def test_matches_personal_rule(self, sample_config, known_logins):
        cwd = Path.home() / "code" / "personal" / "hobby"
        sig = _check_dir_rules(cwd, sample_config, known_logins)
        assert sig is not None
        assert sig.account_label == "personal"

    def test_no_match_returns_none(self, sample_config, known_logins):
        cwd = Path("/tmp/random/dir")
        sig = _check_dir_rules(cwd, sample_config, known_logins)
        assert sig is None


class TestEcosystemFiles:
    def test_package_json_scope(self, tmp_repo, sample_config, known_logins):
        (tmp_repo / "package.json").write_text(
            '{"name": "@work-login/my-pkg"}', encoding="utf-8"
        )
        signals = _check_ecosystem_files(tmp_repo, sample_config, known_logins)
        assert any(s.source == "package-json" for s in signals)

    def test_go_mod(self, tmp_repo, sample_config, known_logins):
        (tmp_repo / "go.mod").write_text(
            "module github.com/work-login/myservice\n\ngo 1.21\n",
            encoding="utf-8",
        )
        signals = _check_ecosystem_files(tmp_repo, sample_config, known_logins)
        assert any(s.source == "go-mod" for s in signals)

    def test_codeowners(self, tmp_repo, sample_config, known_logins):
        gh_dir = tmp_repo / ".github"
        gh_dir.mkdir()
        (gh_dir / "CODEOWNERS").write_text(
            "* @work-login/team-a\nsrc/ @work-login/team-b\n",
            encoding="utf-8",
        )
        signals = _check_ecosystem_files(tmp_repo, sample_config, known_logins)
        assert any(s.source == "codeowners" for s in signals)

    def test_cargo_toml(self, tmp_repo, sample_config, known_logins):
        (tmp_repo / "Cargo.toml").write_text(
            '[package]\nname = "mylib"\nrepository = "https://github.com/work-login/mylib"\n',
            encoding="utf-8",
        )
        signals = _check_ecosystem_files(tmp_repo, sample_config, known_logins)
        assert any(s.source == "cargo-toml" for s in signals)

    def test_funding_yml(self, tmp_repo, sample_config, known_logins):
        gh_dir = tmp_repo / ".github"
        gh_dir.mkdir(exist_ok=True)
        (gh_dir / "FUNDING.yml").write_text(
            "github: personal-login\n", encoding="utf-8"
        )
        signals = _check_ecosystem_files(tmp_repo, sample_config, known_logins)
        assert any(s.source == "funding" for s in signals)

    def test_no_ecosystem_files(self, tmp_repo, sample_config, known_logins):
        signals = _check_ecosystem_files(tmp_repo, sample_config, known_logins)
        assert signals == []


class TestInferAccount:
    def test_repo_override_wins(self, tmp_repo, sample_config, known_logins):
        """Highest-confidence signal (.gh-user) should win."""
        (tmp_repo / ".gh-user").write_text("oss", encoding="utf-8")
        result = infer_account(tmp_repo, sample_config, known_logins)
        assert result.login == "oss-login"
        assert result.signals[0].source == "repo-override"

    def test_falls_back_to_default(self, tmp_path, sample_config, known_logins):
        """With no signals matching, should use global default."""
        result = infer_account(tmp_path, sample_config, known_logins)
        assert result.login == "personal-login"
        assert any(s.source == "global-default" for s in result.all_signals)

    def test_host_default(self, tmp_path, sample_config, known_logins):
        result = infer_account(
            tmp_path, sample_config, known_logins, host="github.enterprise.com"
        )
        # Should prefer host default over global default
        host_signals = [s for s in result.all_signals if s.source == "host-default"]
        global_signals = [s for s in result.all_signals if s.source == "global-default"]
        assert len(host_signals) >= 1
        assert host_signals[0].confidence > global_signals[0].confidence

    def test_empty_config(self, tmp_path):
        """Empty config should return no login."""
        result = infer_account(tmp_path, GhxConfig(), [])
        assert result.login is None
        assert result.all_signals == []
