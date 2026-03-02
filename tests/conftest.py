"""Shared test fixtures for ghx."""

from __future__ import annotations

import pytest
from pathlib import Path

from ghx.config import GhxConfig, BehaviorConfig, Rule, HostConfig


@pytest.fixture
def sample_config() -> GhxConfig:
    """A realistic multi-account config for testing."""
    return GhxConfig(
        accounts={
            "work": "work-login",
            "personal": "personal-login",
            "oss": "oss-login",
        },
        hosts={
            "github.com": HostConfig(default_account="personal"),
            "github.enterprise.com": HostConfig(default_account="work"),
        },
        rules=[
            Rule(path="~/code/work/**", account="work"),
            Rule(path="~/code/personal/**", account="personal"),
            Rule(remote_org="my-company", account="work"),
            Rule(remote_org="my-company", account="work", host="github.enterprise.com"),
            Rule(remote_org="my-personal-org", account="personal"),
        ],
        default_account="personal",
        behavior=BehaviorConfig(
            on_switch_error="warn-and-continue",
            on_undetermined="prompt",
        ),
    )


@pytest.fixture
def known_logins() -> list[str]:
    return ["work-login", "personal-login", "oss-login"]


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Return a temp path for a config file (doesn't create it)."""
    return tmp_path / "config.yml"
