"""Interaction with the gh CLI binary."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass

log = logging.getLogger("ghx")

GH_BIN = os.environ.get("GH_BIN", "gh")


@dataclass
class GhAccount:
    host: str
    login: str
    active: bool


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    log.debug("exec: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=capture, text=True)


def get_accounts(host: str | None = None) -> list[GhAccount]:
    """Query gh auth status and return all known accounts across hosts."""
    cmd = [GH_BIN, "auth", "status"]
    if host:
        cmd += ["--hostname", host]

    # Try JSON output first (gh >= 2.40)
    try:
        proc = _run(cmd + ["--json", "hosts"])
        if proc.returncode == 0 and proc.stdout.strip():
            return _parse_json_status(proc.stdout)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Fall back to text parsing
    proc = _run(cmd)
    if proc.returncode != 0:
        log.warning("gh auth status failed: %s", proc.stderr.strip())
        return []

    return _parse_text_status(proc.stdout + "\n" + proc.stderr)


def _parse_json_status(stdout: str) -> list[GhAccount]:
    """Parse JSON output from gh auth status --json hosts."""
    data = json.loads(stdout)
    accounts: list[GhAccount] = []

    if isinstance(data, dict):
        hosts = data.get("hosts", data)
        if isinstance(hosts, dict):
            for host_name, host_data in hosts.items():
                if isinstance(host_data, list):
                    for entry in host_data:
                        if isinstance(entry, dict) and entry.get("login"):
                            accounts.append(
                                GhAccount(
                                    host=host_name,
                                    login=entry["login"],
                                    active=bool(entry.get("active")),
                                )
                            )
                elif isinstance(host_data, dict) and host_data.get("login"):
                    accounts.append(
                        GhAccount(
                            host=host_name,
                            login=host_data["login"],
                            active=bool(host_data.get("active")),
                        )
                    )
        elif isinstance(hosts, list):
            for entry in hosts:
                if isinstance(entry, dict) and entry.get("login"):
                    accounts.append(
                        GhAccount(
                            host=entry.get("host", "github.com"),
                            login=entry["login"],
                            active=bool(entry.get("active")),
                        )
                    )

    return accounts


def _parse_text_status(output: str) -> list[GhAccount]:
    """Fallback: parse text output from gh auth status."""
    accounts: list[GhAccount] = []
    current_host: str | None = None

    for line in output.splitlines():
        stripped = line.strip()

        # Host line: "github.com" at column 0 or indented, containing a dot, no spaces
        if stripped and "." in stripped and " " not in stripped:
            if not stripped.startswith(("✓", "-", "X", "●")):
                current_host = stripped
                continue

        # Account line: "✓ Logged in to github.com account username (...)"
        if current_host and "Logged in to" in stripped:
            parts = stripped.split("account ")
            if len(parts) > 1:
                login = parts[1].split()[0].strip("()")
                active = "✓" in stripped or "●" in stripped
                accounts.append(
                    GhAccount(host=current_host, login=login, active=active)
                )

    return accounts


def get_active_login(host: str = "github.com") -> str | None:
    """Get the currently active login for a host."""
    accounts = get_accounts(host)
    for acct in accounts:
        if acct.host == host and acct.active:
            return acct.login
    return None


def switch_account(login: str, host: str = "github.com") -> tuple[bool, str]:
    """Switch to a different gh account. Returns (success, message)."""
    cmd = [GH_BIN, "auth", "switch", "--hostname", host, "--user", login]
    proc = _run(cmd)
    if proc.returncode != 0:
        return False, proc.stderr.strip()
    return True, f"Switched to {login} on {host}"


def delegate(args: list[str]) -> int:
    """Replace the current process with gh, passing through all arguments."""
    cmd = [GH_BIN] + args
    log.debug("delegating: %s", " ".join(cmd))
    os.execvp(GH_BIN, cmd)
    return 1  # pragma: no cover — execvp never returns
