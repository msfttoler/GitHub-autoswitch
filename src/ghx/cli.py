#!/usr/bin/env python3
"""ghx — Intelligent GitHub CLI account switcher.

Usage:
    ghx <gh-subcommand> [args...]         # auto-switch + delegate to gh
    ghx status                            # show account status & signals
    ghx init                              # interactive setup wizard
    ghx --gh-user <label> pr create ...   # force account + delegate
    ghx --gh-no-auto pr list              # skip auto-switch, pass through
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ghx.config import CONFIG_DEFAULT_PATH, GhxConfig, load_config
from ghx.gh import GH_BIN, delegate, get_accounts, switch_account
from ghx.inference import infer_account
from ghx.picker import PickerOption, pick_account, simple_prompt
from ghx.status import print_status

log = logging.getLogger("ghx")

# ANSI
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghx",
        description="Intelligent GitHub CLI account switcher",
        add_help=False,
    )
    parser.add_argument(
        "--gh-user",
        dest="gh_user",
        metavar="ACCOUNT",
        help="Force a specific account (label or login)",
    )
    parser.add_argument(
        "--gh-no-auto",
        dest="gh_no_auto",
        action="store_true",
        help="Skip automatic account detection",
    )
    parser.add_argument(
        "--gh-debug",
        dest="gh_debug",
        action="store_true",
        help="Print debug info (signals, subprocess commands)",
    )
    parser.add_argument(
        "--gh-config",
        dest="gh_config",
        metavar="PATH",
        help="Override config file location",
    )
    parser.add_argument(
        "--help", "-h", action="store_true", help="Show this help message"
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)

    ns = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if ns.gh_debug else logging.WARNING,
        format="[ghx] %(message)s",
    )

    if ns.help and not ns.args:
        parser.print_help()
        return 0

    config_path = (
        Path(ns.gh_config).expanduser() if ns.gh_config else CONFIG_DEFAULT_PATH
    )

    # Strip leading -- separator
    args = ns.args
    if args and args[0] == "--":
        args = args[1:]

    # ── Built-in subcommands ──────────────────────────────────────────
    if args and args[0] == "status":
        print_status(config_path)
        return 0

    if args and args[0] == "init":
        return _handle_init(config_path)

    # ── Pass-through mode ─────────────────────────────────────────────
    if ns.gh_no_auto:
        delegate(args or ["--help"])
        return 0  # unreachable

    # ── Load config & accounts ────────────────────────────────────────
    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"[ghx] {RED}Config error: {e}{RESET}", file=sys.stderr)
        config = GhxConfig()

    try:
        accounts = get_accounts()
    except Exception as e:
        log.warning("Failed to get gh accounts: %s", e)
        accounts = []

    known_logins = [a.login for a in accounts]

    # ── Determine target account ──────────────────────────────────────
    target_login = None

    if ns.gh_user:
        target_login = config.resolve_label(ns.gh_user, known_logins)
        if not target_login:
            print(
                f"[ghx] {RED}Cannot resolve account '{ns.gh_user}'{RESET}",
                file=sys.stderr,
            )
            print(
                f"[ghx] Known accounts: {', '.join(known_logins) or '(none)'}",
                file=sys.stderr,
            )
            return 1
    else:
        result = infer_account(Path.cwd(), config, known_logins)

        if result.login:
            target_login = result.login
            log.info("Inferred: %s (%s)", target_login, result.reason)
        elif config.behavior.on_undetermined == "prompt" and accounts:
            target_login = _prompt_account(accounts, config)
        elif config.behavior.on_undetermined == "fallback-default":
            if config.default_account:
                target_login = config.resolve_label(
                    config.default_account, known_logins
                )
        # "skip" → target_login stays None

    # ── Switch if needed ──────────────────────────────────────────────
    if target_login:
        current_active = next(
            (a.login for a in accounts if a.active and a.host == "github.com"),
            None,
        )
        if target_login != current_active:
            success, msg = switch_account(target_login)
            if success:
                log.info("Switched to %s", target_login)
                if ns.gh_debug:
                    print(
                        f"[ghx] {GREEN}Switched to {target_login}{RESET}",
                        file=sys.stderr,
                    )
            else:
                if config.behavior.on_switch_error == "fail":
                    print(f"[ghx] {RED}Switch failed: {msg}{RESET}", file=sys.stderr)
                    return 1
                print(f"[ghx] {YELLOW}Warning: {msg}{RESET}", file=sys.stderr)

    # ── Delegate to gh ────────────────────────────────────────────────
    delegate(args or ["--help"])
    return 0  # unreachable after execvp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prompt_account(accounts: list, config: GhxConfig) -> str | None:
    """Show interactive picker for account selection."""
    options: list[PickerOption] = []
    seen: set[tuple[str, str]] = set()

    for acct in accounts:
        key = (acct.login, acct.host)
        if key in seen:
            continue
        seen.add(key)

        label = None
        for lbl, login in config.accounts.items():
            if login == acct.login:
                label = lbl
                break

        options.append(
            PickerOption(
                login=acct.login,
                label=label,
                host=acct.host,
                active=acct.active,
            )
        )

    if not options:
        return None

    try:
        result = pick_account(options, "Which account for this directory?")
    except Exception:
        result = simple_prompt(options, "Which account for this directory?")

    return result.login if result else None


def _handle_init(config_path: Path) -> int:
    """Interactive setup wizard."""
    print(f"\n{BOLD}{CYAN}  ghx init — Setup Wizard{RESET}\n")

    if config_path.exists():
        print(f"  Config already exists: {config_path}")
        try:
            answer = input("  Overwrite? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 1
        if answer != "y":
            print("  Aborted.")
            return 0

    # Discover accounts
    print(f"  {DIM}Discovering gh accounts...{RESET}")
    accounts = get_accounts()
    if not accounts:
        print(f"\n  {RED}No accounts found. Run 'gh auth login' first.{RESET}")
        return 1

    print(f"  Found {len(accounts)} account(s):\n")

    labels: dict[str, str] = {}
    for acct in accounts:
        active = " (active)" if acct.active else ""
        host_str = f" [{acct.host}]" if acct.host != "github.com" else ""
        print(f"    {acct.login}{host_str}{active}")
        try:
            label = input(
                f"    Label for {acct.login} (e.g., work/personal/oss): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return 1
        if label:
            labels[label] = acct.login

    # Build config YAML
    lines = ["# ghx configuration — generated by ghx init\n"]

    lines.append("accounts:")
    for label, login in labels.items():
        lines.append(f"  {label}: {login}")
    lines.append("")

    # Host defaults
    hosts_seen = {a.host for a in accounts}
    if hosts_seen:
        lines.append("hosts:")
        for host in sorted(hosts_seen):
            default = next(
                (
                    lbl
                    for lbl, login in labels.items()
                    if any(
                        a.login == login and a.host == host and a.active
                        for a in accounts
                    )
                ),
                None,
            )
            if default:
                lines.append(f"  {host}:")
                lines.append(f"    default_account: {default}")
        lines.append("")

    lines.append("rules:")
    lines.append("  # Directory-based rules (first match wins):")
    lines.append('  # - path: "~/code/work/**"')
    lines.append("  #   account: work")
    lines.append("  #")
    lines.append("  # Git remote org rules:")
    lines.append("  # - remote_org: my-company")
    lines.append("  #   account: work")
    lines.append("")

    if labels:
        first_label = next(iter(labels))
        lines.append(f"default_account: {first_label}")
    lines.append("")

    lines.append("behavior:")
    lines.append("  on_switch_error: warn-and-continue")
    lines.append("  on_undetermined: prompt")
    lines.append("")

    config_content = "\n".join(lines)

    # Write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_content, encoding="utf-8")

    print(f"\n  {GREEN}✓ Config written to {config_path}{RESET}")
    print(f"  {DIM}Edit it to add directory rules and remote org mappings.{RESET}\n")
    return 0


def entry_point() -> None:
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    entry_point()
