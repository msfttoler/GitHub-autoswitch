"""Intelligent account inference engine.

Evaluates multiple signals to determine which GitHub account
should be active for the current working directory.

Signal priority (highest confidence first):
  1. .gh-user file in repo root              (1.0)
  2. Directory path rules from config        (0.9)
  3. Git remote org/owner rules              (0.85)
  4. Git remote org → direct account match   (0.6)
  5. Ecosystem file hints (CODEOWNERS, etc.) (0.5)
  6. Per-host default from config            (0.3)
  7. Global default from config              (0.2)
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ghx.config import GhxConfig

log = logging.getLogger("ghx")


@dataclass
class Signal:
    """A single piece of evidence pointing to an account."""

    source: str  # e.g., "repo-override", "dir-rule", "remote-org"
    account_label: str
    detail: str  # human-readable explanation
    confidence: float = 1.0  # 0.0–1.0


@dataclass
class InferenceResult:
    """Result of the inference engine."""

    login: str | None = None
    host: str = "github.com"
    signals: list[Signal] = field(default_factory=list)
    all_signals: list[Signal] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if not self.signals:
            return "no signals matched"
        return self.signals[0].detail


def infer_account(
    cwd: Path,
    config: GhxConfig,
    known_logins: list[str] | None = None,
    host: str = "github.com",
) -> InferenceResult:
    """Run the full inference chain and return the best account match."""
    result = InferenceResult(host=host)
    signals: list[Signal] = []

    repo_root = _find_repo_root(cwd)

    # 1. Repo override file (.gh-user)
    sig = _check_repo_override(repo_root, config, known_logins)
    if sig:
        signals.append(sig)

    # 2. Directory path rules
    sig = _check_dir_rules(cwd, config, known_logins)
    if sig:
        signals.append(sig)

    # 3. Git remote org/owner
    remote_signals = _check_git_remote(repo_root, config, known_logins, host)
    signals.extend(remote_signals)

    # 4. Ecosystem file hints
    if repo_root:
        eco_signals = _check_ecosystem_files(repo_root, config, known_logins)
        signals.extend(eco_signals)

    # 5. Per-host default
    host_default = config.get_host_default(host)
    if host_default:
        login = config.resolve_label(host_default, known_logins)
        if login:
            signals.append(
                Signal(
                    source="host-default",
                    account_label=host_default,
                    detail=f"Host default for {host}: {host_default}",
                    confidence=0.3,
                )
            )

    # 6. Global default
    if config.default_account:
        login = config.resolve_label(config.default_account, known_logins)
        if login:
            signals.append(
                Signal(
                    source="global-default",
                    account_label=config.default_account,
                    detail=f"Global default: {config.default_account}",
                    confidence=0.2,
                )
            )

    result.all_signals = signals

    # Pick the highest-confidence signal
    if signals:
        best = max(signals, key=lambda s: s.confidence)
        result.login = config.resolve_label(best.account_label, known_logins)
        result.signals = [s for s in signals if s.confidence == best.confidence]

    return result


# ---------------------------------------------------------------------------
# Signal checkers
# ---------------------------------------------------------------------------


def _find_repo_root(start: Path) -> Path | None:
    """Walk up from start to find the nearest .git directory."""
    current = start.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _check_repo_override(
    repo_root: Path | None,
    config: GhxConfig,
    known_logins: list[str] | None,
) -> Signal | None:
    """Check for .gh-user file in the repo root."""
    if not repo_root:
        return None

    marker = repo_root / ".gh-user"
    if not marker.exists():
        return None

    label = marker.read_text(encoding="utf-8").strip()
    if not label:
        return None

    login = config.resolve_label(label, known_logins)
    if login:
        return Signal(
            source="repo-override",
            account_label=label,
            detail=f".gh-user file specifies: {label}",
            confidence=1.0,
        )

    log.warning(
        ".gh-user contains '%s' but it doesn't resolve to a known account", label
    )
    return None


def _check_dir_rules(
    cwd: Path,
    config: GhxConfig,
    known_logins: list[str] | None,
) -> Signal | None:
    """Check directory path rules (first match wins)."""
    cwd_str = str(cwd.resolve())

    for rule in config.rules:
        if not rule.path or not rule.account:
            continue

        pattern = os.path.expanduser(rule.path)

        # Handle ** suffix patterns as prefix matches
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if cwd_str.startswith(prefix) or cwd_str == prefix.rstrip("/"):
                login = config.resolve_label(rule.account, known_logins)
                if login:
                    return Signal(
                        source="dir-rule",
                        account_label=rule.account,
                        detail=f"Directory matches rule: {rule.path}",
                        confidence=0.9,
                    )
        elif fnmatch.fnmatch(cwd_str, pattern):
            login = config.resolve_label(rule.account, known_logins)
            if login:
                return Signal(
                    source="dir-rule",
                    account_label=rule.account,
                    detail=f"Directory matches rule: {rule.path}",
                    confidence=0.9,
                )

    return None


def _check_git_remote(
    repo_root: Path | None,
    config: GhxConfig,
    known_logins: list[str] | None,
    target_host: str,
) -> list[Signal]:
    """Parse git remote URL to extract org/owner and match against rules."""
    if not repo_root:
        return []

    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if proc.returncode != 0:
            return []
    except FileNotFoundError:
        return []

    remote_url = proc.stdout.strip()
    if not remote_url:
        return []

    host, org, repo = _parse_remote_url(remote_url)
    if not org:
        return []

    log.debug("Git remote: host=%s org=%s repo=%s", host, org, repo)

    signals: list[Signal] = []

    # Check remote_org rules in config
    for rule in config.rules:
        if not rule.remote_org or not rule.account:
            continue

        rule_host = rule.host or "github.com"
        if rule.remote_org.lower() == org.lower() and (host or "github.com") == rule_host:
            login = config.resolve_label(rule.account, known_logins)
            if login:
                signals.append(
                    Signal(
                        source="remote-org",
                        account_label=rule.account,
                        detail=f"Git remote org '{org}' matches rule → {rule.account}",
                        confidence=0.85,
                    )
                )

    # Direct match: org name matches a known account login
    if not signals:
        login = config.resolve_label(org, known_logins)
        if login:
            signals.append(
                Signal(
                    source="remote-org-direct",
                    account_label=org,
                    detail=f"Git remote org '{org}' matches account login directly",
                    confidence=0.6,
                )
            )

    return signals


def _parse_remote_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Parse a git remote URL into (host, org, repo).

    Supports:
      - https://github.com/org/repo.git
      - git@github.com:org/repo.git
      - ssh://git@github.com/org/repo.git
    """
    # HTTPS
    m = re.match(r"https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)

    # SSH shorthand: git@host:org/repo.git
    m = re.match(r"git@([^:]+):([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)

    # SSH URL: ssh://git@host/org/repo.git
    m = re.match(r"ssh://[^@]+@([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)

    return None, None, None


def _check_ecosystem_files(
    repo_root: Path,
    config: GhxConfig,
    known_logins: list[str] | None,
) -> list[Signal]:
    """Scan repository files for org/owner hints.

    Checks:
      - CODEOWNERS for @org/ team patterns
      - package.json for @scope packages
      - go.mod for module path org
      - .github/FUNDING.yml for github usernames
      - Cargo.toml for repository URL org
    """
    signals: list[Signal] = []

    # CODEOWNERS
    for codeowners_path in [
        repo_root / "CODEOWNERS",
        repo_root / ".github" / "CODEOWNERS",
        repo_root / "docs" / "CODEOWNERS",
    ]:
        if codeowners_path.exists():
            try:
                content = codeowners_path.read_text(encoding="utf-8")
                orgs = set(re.findall(r"@([a-zA-Z0-9_-]+)/", content))
                for org in orgs:
                    login = config.resolve_label(org, known_logins)
                    if login:
                        signals.append(
                            Signal(
                                source="codeowners",
                                account_label=org,
                                detail=f"CODEOWNERS references @{org}/ teams",
                                confidence=0.5,
                            )
                        )
            except OSError:
                pass
            break

    # package.json (npm org scope)
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            name = data.get("name", "")
            if name.startswith("@"):
                scope = name.split("/")[0][1:]  # remove @
                login = config.resolve_label(scope, known_logins)
                if login:
                    signals.append(
                        Signal(
                            source="package-json",
                            account_label=scope,
                            detail=f"package.json scope @{scope}",
                            confidence=0.5,
                        )
                    )
        except (OSError, json.JSONDecodeError):
            pass

    # go.mod
    go_mod = repo_root / "go.mod"
    if go_mod.exists():
        try:
            content = go_mod.read_text(encoding="utf-8")
            m = re.match(r"module\s+github\.com/([^/\s]+)", content)
            if m:
                org = m.group(1)
                login = config.resolve_label(org, known_logins)
                if login:
                    signals.append(
                        Signal(
                            source="go-mod",
                            account_label=org,
                            detail=f"go.mod module path: github.com/{org}/...",
                            confidence=0.5,
                        )
                    )
        except OSError:
            pass

    # Cargo.toml (Rust — check repository URL)
    cargo_toml = repo_root / "Cargo.toml"
    if cargo_toml.exists():
        try:
            content = cargo_toml.read_text(encoding="utf-8")
            m = re.search(
                r'repository\s*=\s*"https?://github\.com/([^/"]+)', content
            )
            if m:
                org = m.group(1)
                login = config.resolve_label(org, known_logins)
                if login:
                    signals.append(
                        Signal(
                            source="cargo-toml",
                            account_label=org,
                            detail=f"Cargo.toml repository: github.com/{org}/...",
                            confidence=0.5,
                        )
                    )
        except OSError:
            pass

    # .github/FUNDING.yml
    funding = repo_root / ".github" / "FUNDING.yml"
    if funding.exists():
        try:
            content = funding.read_text(encoding="utf-8")
            m = re.search(r"github:\s*\[?([a-zA-Z0-9_-]+)", content)
            if m:
                username = m.group(1)
                login = config.resolve_label(username, known_logins)
                if login:
                    signals.append(
                        Signal(
                            source="funding",
                            account_label=username,
                            detail=f"FUNDING.yml github sponsor: {username}",
                            confidence=0.4,
                        )
                    )
        except OSError:
            pass

    return signals
