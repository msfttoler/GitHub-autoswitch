"""Tests for ghx.gh module."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from ghx.gh import (
    GhAccount,
    get_accounts,
    get_active_login,
    switch_account,
    _parse_json_status,
    _parse_text_status,
)


class TestParseJsonStatus:
    def test_dict_of_lists(self):
        """gh auth status --json hosts with hosts as dict of lists."""
        data = json.dumps(
            {
                "hosts": {
                    "github.com": [
                        {"login": "alice", "active": True},
                        {"login": "bob", "active": False},
                    ],
                    "github.enterprise.com": [
                        {"login": "alice-work", "active": True},
                    ],
                }
            }
        )
        accounts = _parse_json_status(data)
        assert len(accounts) == 3
        assert accounts[0] == GhAccount("github.com", "alice", True)
        assert accounts[1] == GhAccount("github.com", "bob", False)
        assert accounts[2] == GhAccount("github.enterprise.com", "alice-work", True)

    def test_flat_list(self):
        """gh auth status --json hosts returning flat list of dicts."""
        data = json.dumps(
            {
                "hosts": [
                    {"host": "github.com", "login": "alice", "active": True},
                    {"host": "github.com", "login": "bob", "active": False},
                ]
            }
        )
        accounts = _parse_json_status(data)
        assert len(accounts) == 2
        assert accounts[0].login == "alice"
        assert accounts[0].active is True

    def test_empty_json(self):
        accounts = _parse_json_status("{}")
        assert accounts == []


class TestParseTextStatus:
    def test_typical_output(self):
        text = """\
github.com
  ✓ Logged in to github.com account alice (keyring)
  - Logged in to github.com account bob (token)
"""
        accounts = _parse_text_status(text)
        assert len(accounts) == 2
        assert accounts[0].login == "alice"
        assert accounts[0].active is True
        assert accounts[1].login == "bob"
        assert accounts[1].active is False

    def test_empty_output(self):
        assert _parse_text_status("") == []


class TestGetAccounts:
    @patch("ghx.gh._run")
    def test_json_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "hosts": {
                        "github.com": [
                            {"login": "alice", "active": True},
                        ]
                    }
                }
            ),
        )
        accounts = get_accounts()
        assert len(accounts) == 1
        assert accounts[0].login == "alice"

    @patch("ghx.gh._run")
    def test_json_fails_falls_back_to_text(self, mock_run):
        """If JSON output fails, should fall back to text parsing."""
        # First call (JSON) fails, second call (text) succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="not supported"),
            MagicMock(
                returncode=0,
                stdout="github.com\n  ✓ Logged in to github.com account alice (keyring)\n",
                stderr="",
            ),
        ]
        accounts = get_accounts()
        assert len(accounts) == 1
        assert accounts[0].login == "alice"


class TestSwitchAccount:
    @patch("ghx.gh._run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        success, msg = switch_account("alice")
        assert success is True
        assert "alice" in msg

    @patch("ghx.gh._run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="account not found"
        )
        success, msg = switch_account("nonexistent")
        assert success is False
        assert "not found" in msg


class TestGetActiveLogin:
    @patch("ghx.gh.get_accounts")
    def test_returns_active(self, mock_get):
        mock_get.return_value = [
            GhAccount("github.com", "alice", True),
            GhAccount("github.com", "bob", False),
        ]
        assert get_active_login("github.com") == "alice"

    @patch("ghx.gh.get_accounts")
    def test_returns_none_when_no_active(self, mock_get):
        mock_get.return_value = [
            GhAccount("github.com", "alice", False),
        ]
        assert get_active_login("github.com") is None
