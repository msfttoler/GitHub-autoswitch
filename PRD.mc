## 1. Technical Approach (Python)

- Implement a **Python CLI** (e.g., `ghx`) that:
  - Parses wrapper‑only flags.
  - Computes the desired account.
  - Ensures `gh` is switched to that account via `gh auth switch`.[1][2][3]
  - Delegates the original `gh` command via `subprocess`.

- Use `gh auth status --hostname github.com --json hosts` and parse JSON to discover accounts and the current active one.[3][4][5][6]

- Distribute as a single script or small package, plus a shell alias to shadow `gh` if desired.

***

## 2. Python‑Specific Functional Requirements

### FR‑P1: Python CLI entrypoint

- Provide a console entry point, e.g., `ghx`, via `setup.py` / `pyproject.toml`.
- Invocation patterns:
  - `ghx <gh-subcommand> [args...]`
  - `ghx --gh-debug pr create`
  - Optional: alias `gh=ghx` in shell.

### FR‑P2: `gh auth status` integration

- Invoke `gh auth status --hostname github.com --json hosts` and parse stdout as JSON.[4][5][6][3]
- Extract, for `github.com`:
  - List of accounts (`login`).
  - Which one is `active` if present (field name depends on JSON structure; robust parsing needed based on `hosts` structure).[5][4]
- On parse error or missing `gh`, return a structured error and (configurable) fallback.

### FR‑P3: Switching accounts from Python

- When a target login is selected:
  - Run `gh auth switch --hostname github.com --user <login>` using `subprocess.run`.[2][1][3]
  - Check `returncode` and stderr:
    - On non‑zero, display helpful message and optionally abort or continue without switching, based on config.

### FR‑P4: Config management in Python

- Config path: `~/.config/ghx/config.yml` (or `gh-wrapper` from previous PRD).
- Use `pyyaml` or standard library (`json`) for config; YAML preferred for readability.
- Config schema:
  ```yaml
  accounts:
    work: work-login
    personal: personal-login
  rules:
    - path: "~/code/work/**"
      account: "work"
    - path: "~/code/personal/**"
      account: "personal"
  default_account: "personal"
  behavior:
    on_switch_error: "warn-and-continue"  # or "fail"
    on_undetermined: "prompt"             # or "fallback-default"
  ```
- Python logic loads and validates config on each run, with caching in a global singleton for the process.

### FR‑P5: Signal evaluation in Python

- **Per‑repo file:**
  - Check for `.gh-user` in the repo root (walk up from `cwd` until `.git` found).
  - If present, read label/login and resolve via `accounts` mapping.
- **Directory rules:**
  - Expand `~` and glob patterns using `pathlib` and `fnmatch`.
  - First matching rule wins.
- **Git remote inspection:**
  - Run `git remote get-url origin` via `subprocess`.
  - Parse owner/org and map via config (e.g., `owner_prefixes` → account label).
- Implement a Python function:
  ```python
  def infer_account_for_cwd(config) -> Optional[str]:
      ...
  ```
  returning a login (not just label) or `None`.

### FR‑P6: Status command (`ghx status`)

- Implement a Python subcommand:
  - `ghx status`
- Outputs:
  - Accounts from `gh auth status` (host, login, active flag).[3][4][5]
  - Current directory.
  - Inferred logical account + login and which signals fired.

***

## 3. Python CLI UX and Flags

Wrapper‑only flags (parsed by Python, not passed to `gh`):

- `--gh-user <label-or-login>`: force account.
- `--gh-no-auto`: disable detection; directly run `gh`.
- `--gh-debug`: print internal decisions and subprocess commands.
- `--gh-config <path>`: override config file location (useful in tests).

Implementation detail:

- Parse wrapper flags first (e.g., via `argparse` with `parse_known_args`).
- Remaining args are passed to `gh` as‑is.

***

## 4. Error Handling & Logging (Python‑specific)

- Use a simple logger (e.g., `logging` module) with levels:
  - ERROR: subprocess failures or invalid config.
  - INFO: high‑level decisions when `--gh-debug` is on.
- On `gh auth status` failure:
  - If `on_undetermined == "fallback-default"`, use default account if available.
  - Else, print message and run `gh` unmodified or abort (configurable).

***

## 5. Skeleton Python Implementation (Illustrative)

```python
#!/usr/bin/env python3
import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # require in packaging

log = logging.getLogger("ghx")

CONFIG_DEFAULT = Path("~/.config/ghx/config.yml").expanduser()
GH_BIN = os.environ.get("GH_BIN", "gh")
GITHUB_HOST = "github.com"


def run(cmd, check=False, capture_output=False, text=True):
    log.debug("run: %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required to read config files.")
    with path.open() as f:
        return yaml.safe_load(f) or {}


def get_gh_accounts():
    """Return (accounts, active_login?) for github.com via gh auth status JSON."""
    try:
        proc = run(
            [GH_BIN, "auth", "status", "--hostname", GITHUB_HOST, "--json", "hosts"],
            capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError("gh binary not found in PATH")

    if proc.returncode != 0:
        raise RuntimeError(f"`gh auth status` failed: {proc.stderr.strip()}")

    data = json.loads(proc.stdout or "{}")
    hosts = data.get("hosts") or data.get(GITHUB_HOST) or []
    accounts = []
    active_login = None

    # JSON structure may evolve; be defensive
    for host_entry in hosts:
        if isinstance(host_entry, dict):
            if host_entry.get("host") != GITHUB_HOST and GITHUB_HOST in 
                # old structure indexed by hostname
                continue
            login = host_entry.get("login")
            if login:
                accounts.append(login)
            if host_entry.get("active"):
                active_login = login

    return accounts, active_login


def find_repo_root(start: Path) -> Path | None:
    current = start
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def read_repo_override(root: Path) -> str | None:
    marker = root / ".gh-user"
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip() or None
    return None


def resolve_label_to_login(label_or_login: str, config: dict, accounts: list[str]) -> str | None:
    accounts_map = (config.get("accounts") or {}) if isinstance(config, dict) else {}
    # If matches label
    if label_or_login in accounts_map:
        return accounts_map[label_or_login]
    # If matches known login
    if label_or_login in accounts:
        return label_or_login
    return None


def infer_account_for_cwd(cwd: Path, config: dict, accounts: list[str]) -> str | None:
    # 1. Repo override
    root = find_repo_root(cwd)
    if root:
        label = read_repo_override(root)
        if label:
            login = resolve_label_to_login(label, config, accounts)
            if login:
                log.debug("repo override: %s -> %s", label, login)
                return login

    # 2. Directory rules
    rules = config.get("rules") or []
    for rule in rules:
        path_pattern = os.path.expanduser(rule.get("path", ""))
        account_label = rule.get("account")
        if not path_pattern or not account_label:
            continue
        # naive prefix match; could be improved with fnmatch or glob
        pattern_path = Path(path_pattern.replace("**", "")).expanduser()
        if str(cwd).startswith(str(pattern_path)):
            login = resolve_label_to_login(account_label, config, accounts)
            if login:
                log.debug("dir rule matched: %s -> %s", account_label, login)
                return login

    # 3. Fallback default
    default_label = config.get("default_account")
    if default_label:
        login = resolve_label_to_login(default_label, config, accounts)
        if login:
            log.debug("default account: %s -> %s", default_label, login)
            return login

    return None


def ensure_account(login: str, current_active: str | None, behavior: dict):
    if login == current_active:
        log.debug("already active account: %s", login)
        return

    cmd = [GH_BIN, "auth", "switch", "--hostname", GITHUB_HOST, "--user", login]
    proc = run(cmd, capture_output=True)
    if proc.returncode != 0:
        mode = (behavior or {}).get("on_switch_error", "warn-and-continue")
        msg = f"gh auth switch failed for {login}: {proc.stderr.strip()}"
        if mode == "fail":
            raise RuntimeError(msg)
        else:
            print(f"[ghx] warning: {msg}", file=sys.stderr)


def handle_status(config_path: Path):
    config = load_config(config_path)
    accounts, active = get_gh_accounts()
    cwd = Path.cwd()
    inferred = infer_account_for_cwd(cwd, config, accounts)

    print(f"Host: {GITHUB_HOST}")
    print(f"Accounts: {', '.join(accounts) or '(none)'}")
    print(f"Active: {active or '(none)'}")
    print(f"Dir: {cwd}")
    print(f"Inferred account for this dir: {inferred or '(none)'}")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--gh-user", dest="gh_user", help="Force GH account (label or login)")
    parser.add_argument("--gh-no-auto", action="store_true", help="Disable auto account selection")
    parser.add_argument("--gh-debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--gh-config", dest="gh_config", help="Path to config file")
    parser.add_argument("args", nargs=argparse.REMAINDER)

    ns = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if ns.gh_debug else logging.WARNING)

    config_path = Path(ns.gh_config).expanduser() if ns.gh_config else CONFIG_DEFAULT

    # Special: status command
    if ns.args and ns.args[0] == "status" and (len(ns.args) == 1 or ns.args[1] in ("", "--")):
        handle_status(config_path)
        return

    # If no arguments, just pass through to gh
    if not ns.args:
        gh_cmd = [GH_BIN]
    else:
        if ns.args and ns.args[0] == "--":
            gh_cmd = [GH_BIN] + ns.args[1:]
        else:
            gh_cmd = [GH_BIN] + ns.args

    if ns.gh_no_auto:
        os.execvp(GH_BIN, gh_cmd)

    config = load_config(config_path)
    accounts, active = get_gh_accounts()
    behavior = (config or {}).get("behavior") or {}

    # Determine desired account
    target_login = None
    if ns.gh_user:
        target_login = resolve_label_to_login(ns.gh_user, config, accounts)
        if not target_login:
            print(f"[ghx] error: cannot resolve account '{ns.gh_user}'", file=sys.stderr)
            sys.exit(1)
    else:
        target_login = infer_account_for_cwd(Path.cwd(), config, accounts)

    if target_login:
        ensure_account(target_login, active, behavior)

    # Delegate to gh (replace current process)
    os.execvp(GH_BIN, gh_cmd)


if __name__ == "__main__":
    main()
```
