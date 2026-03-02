"""Status display for ghx — shows accounts, inference signals, and context."""

from __future__ import annotations

from pathlib import Path

from ghx.config import GhxConfig, load_config
from ghx.gh import get_accounts
from ghx.inference import infer_account

# ANSI
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"


def print_status(config_path: Path | None = None) -> None:
    """Print a comprehensive status overview."""
    config = load_config(config_path)
    accounts = get_accounts()
    cwd = Path.cwd()

    # Group by host
    hosts: dict[str, list] = {}
    for acct in accounts:
        hosts.setdefault(acct.host, []).append(acct)

    known_logins = [a.login for a in accounts]

    print(f"\n{BOLD}{CYAN}  ghx status{RESET}\n")

    # --- Accounts ---
    if not accounts:
        print(f"  {RED}No gh accounts found.{RESET}")
        print(f"  {DIM}Run 'gh auth login' to add accounts.{RESET}\n")
        return

    for host, host_accounts in sorted(hosts.items()):
        print(f"  {BOLD}{host}{RESET}")
        for acct in host_accounts:
            active_marker = f" {GREEN}● active{RESET}" if acct.active else ""
            label = _find_label(acct.login, config)
            label_str = f" {DIM}({label}){RESET}" if label else ""
            print(f"    {acct.login}{label_str}{active_marker}")
        print()

    # --- Current directory ---
    print(f"  {BOLD}Directory:{RESET} {cwd}\n")

    # --- Inference for each host ---
    for host in sorted(hosts):
        result = infer_account(cwd, config, known_logins, host)

        if result.login:
            print(f"  {BOLD}Inferred for {host}:{RESET} {GREEN}{result.login}{RESET}")
            for sig in result.all_signals:
                is_winner = sig in result.signals
                marker = "→" if is_winner else " "
                bar = _confidence_bar(sig.confidence)
                color = "" if is_winner else DIM
                print(f"    {marker} {bar} {color}{sig.detail}{RESET}")
        else:
            print(f"  {BOLD}Inferred for {host}:{RESET} {YELLOW}(none){RESET}")
            if result.all_signals:
                for sig in result.all_signals:
                    bar = _confidence_bar(sig.confidence)
                    print(f"      {bar} {DIM}{sig.detail}{RESET}")

        print()


def _find_label(login: str, config: GhxConfig) -> str | None:
    """Find the config label for a login."""
    for label, mapped_login in config.accounts.items():
        if mapped_login == login:
            return label
    return None


def _confidence_bar(confidence: float) -> str:
    """Visual confidence indicator."""
    filled = int(confidence * 5)
    return f"{DIM}[{'█' * filled}{'░' * (5 - filled)}]{RESET}"
