# ghx — Intelligent GitHub CLI Account Switcher

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

**Automatically switch between multiple GitHub accounts based on where you are.**

If you juggle work, personal, and OSS GitHub accounts, `ghx` makes `gh` just work — it detects which account you should be using based on your directory, git remote, project files, and config rules, then silently switches before running your command.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Inference Engine](#inference-engine)
- [VS Code Extension](#vs-code-extension)
- [Shell Completions](#shell-completions)
- [Architecture](#architecture)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [License](#license)

---

## How It Works

`ghx` is a transparent wrapper around the [GitHub CLI (`gh`)](https://cli.github.com/). Every time you run a command through `ghx`, it:

1. **Collects signals** from your environment — the current directory, git remote URL, repo-level override files, ecosystem project files, and your configuration rules.
2. **Evaluates** each signal with a confidence score (0.0–1.0) using a priority-ordered inference engine.
3. **Selects the best account** — the signal with the highest confidence determines which GitHub account to use.
4. **Switches accounts** by running `gh auth switch` if the active account differs from the inferred one.
5. **Delegates** the original command to `gh` via `os.execvp`, replacing the current process so `gh` takes over completely.

All of this happens in milliseconds. You alias `gh=ghx` and forget about it.

```
┌──────────────────────────────────┐
│  You run: gh pr create           │
│  (aliased to ghx)                │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  1. Parse wrapper flags          │
│     (--gh-user, --gh-debug, etc) │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  2. Load ~/.config/ghx/config.yml│
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  3. Run inference engine:        │
│     • .gh-user file     (1.0)    │
│     • Directory rules   (0.9)    │
│     • Git remote org    (0.85)   │
│     • Ecosystem files   (0.5)    │
│     • Host default      (0.3)    │
│     • Global default    (0.2)    │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  4. gh auth switch --user <acct> │
│     (only if active ≠ inferred)  │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  5. os.execvp("gh", ["gh",      │
│     "pr", "create"])             │
│     → ghx process is replaced   │
└──────────────────────────────────┘
```

---

## Features

### Terminal CLI (`ghx`)

- **Smart inference** — determines the right account from `.gh-user` files, directory rules, git remote org/owner, ecosystem files (CODEOWNERS, package.json, go.mod, Cargo.toml, FUNDING.yml), and configurable defaults
- **Transparent proxy** — wraps `gh` seamlessly; alias `gh=ghx` and forget
- **Interactive picker** — full arrow-key account selector (with vim key support) when rules can't determine the right account
- **Multi-host support** — works with github.com and GitHub Enterprise Server
- **Zero friction** — configure once, never think about it again
- **Shell completions** — tab completion for Bash, Zsh, and Fish
- **Debug mode** — `--gh-debug` shows exactly which signals fired and why

### VS Code Extension

- **`@ghx` Copilot Chat Participant** — ask about your accounts in natural language
  - `/status` — see all accounts and inference signals
  - `/why` — LLM-powered explanation of why an account was selected
  - `/switch <account>` — switch accounts from chat
  - `/setup` — AI-assisted configuration generation
- **Status bar indicator** — always see which account is active, with a warning icon when it doesn't match the inferred account
- **Auto-switch on workspace open** — silently switches to the right account when you open a project
- **Quick Pick command** — `ghx.switchAccount` lets you switch accounts from the command palette

---

## Prerequisites

- **[GitHub CLI (`gh`)](https://cli.github.com/)** ≥ 2.40 (for JSON output; older versions fall back to text parsing)
- **Python** ≥ 3.10
- **Git** (for remote URL inference)
- **Multiple `gh` accounts** — log in with `gh auth login` for each account you want to use

```bash
# Verify prerequisites
gh --version        # should be ≥ 2.40
python3 --version   # should be ≥ 3.10
git --version

# Log in to multiple accounts
gh auth login                              # first account
gh auth login --hostname github.com        # second account
gh auth login --hostname github.myco.com   # enterprise account
```

---

## Installation

### From Source (recommended for development)

```bash
git clone https://github.com/msfttoler/GitHub-autoswitch.git
cd GitHub-autoswitch
pip install .
```

### With development dependencies

```bash
pip install ".[dev]"
```

### From PyPI (when published)

```bash
pip install ghx
```

### Verify installation

```bash
ghx --help
ghx status
```

---

## Configuration

### Quick Setup

Run the interactive setup wizard — it discovers your `gh` accounts and walks you through labeling them:

```bash
ghx init
```

This creates `~/.config/ghx/config.yml` with your accounts, host defaults, and placeholder rules.

### Manual Configuration

Create or edit `~/.config/ghx/config.yml`:

```yaml
# ── Account labels ────────────────────────────────────────────
# Map friendly labels to GitHub login usernames.
# These labels are used in rules and the --gh-user flag.
accounts:
  work: work-login
  personal: personal-login
  oss: oss-login

# ── Per-host defaults ────────────────────────────────────────
# Set which account is the default for each GitHub host.
# Supports GitHub Enterprise Server instances.
hosts:
  github.com:
    default_account: personal
  github.mycompany.com:
    default_account: work

# ── Rules (first match wins) ─────────────────────────────────
# Rules are evaluated top-to-bottom. The first matching rule
# determines the account. Confidence scores are assigned
# automatically based on rule type.
rules:
  # Directory-based rules: match by current working directory
  - path: "~/code/work/**"
    account: work
  - path: "~/code/personal/**"
    account: personal

  # Git remote org/owner rules: match by GitHub org in the remote URL
  - remote_org: my-company
    account: work
  - remote_org: my-personal-org
    account: personal

  # Enterprise host rule: match org + specific host
  - remote_org: my-company
    account: work
    host: github.mycompany.com

# ── Fallback ─────────────────────────────────────────────────
# Used when no signals or rules produce a match.
default_account: personal

# ── Behavior ─────────────────────────────────────────────────
behavior:
  # What to do when `gh auth switch` fails:
  #   warn-and-continue — print a warning, run the command anyway
  #   fail              — abort with a non-zero exit code
  on_switch_error: warn-and-continue

  # What to do when no account can be determined:
  #   prompt           — show an interactive account picker
  #   fallback-default — silently use the default_account
  #   skip             — run gh without switching
  on_undetermined: prompt
```

### Per-Repository Override

Place a `.gh-user` file in any repository root (next to `.git/`) to hard-pin an account:

```bash
cd ~/code/work/secret-project
echo "work" > .gh-user
```

This is the highest-priority signal (confidence 1.0) and overrides all rules.

> **Tip:** Add `.gh-user` to your global `.gitignore` so it never gets committed:
> ```bash
> echo ".gh-user" >> ~/.gitignore
> ```

---

## Usage

### Basic Usage

```bash
# Just use gh as normal — ghx handles the rest
ghx pr create
ghx issue list
ghx repo view

# Or alias it (add to your shell profile)
alias gh=ghx
gh pr create   # ← auto-switches account based on where you are
```

### Wrapper Flags

`ghx` adds its own flags that are intercepted before any arguments reach `gh`:

| Flag | Description |
|------|-------------|
| `--gh-user <label>` | Force a specific account by label or login |
| `--gh-no-auto` | Skip auto-detection; pass command directly to `gh` |
| `--gh-debug` | Print inference decisions and subprocess commands |
| `--gh-config <path>` | Use an alternate config file |
| `--help` / `-h` | Show ghx help |

```bash
# Force a specific account
ghx --gh-user work pr create

# Skip auto-switching entirely
ghx --gh-no-auto issue list

# Debug: see what ghx is thinking
ghx --gh-debug pr create

# Use a different config file
ghx --gh-config ~/custom-config.yml status
```

### Built-in Subcommands

| Command | Description |
|---------|-------------|
| `ghx status` | Show all accounts, current directory, and which signals fired |
| `ghx init` | Interactive setup wizard to create or overwrite your config |

#### `ghx status` Output

```
  ghx status

  github.com
    work-login (work) ● active
    personal-login (personal)

  Directory: /Users/you/code/work/my-project

  Inferred for github.com: work-login
    → [█████] .gh-user file specifies: work
      [████░] Directory matches rule: ~/code/work/**
      [████░] Git remote org 'my-company' matches rule → work
      [█░░░░] Host default for github.com: personal
      [█░░░░] Global default: personal
```

---

## Inference Engine

The inference engine evaluates multiple signals to determine which account to use. Each signal has a confidence score from 0.0 to 1.0. The signal with the highest confidence wins.

### Signal Priority

| Priority | Signal | Confidence | Source |
|----------|--------|------------|--------|
| 1 | `.gh-user` file in repo root | **1.0** | Per-repository override file |
| 2 | Directory path rules | **0.9** | `rules[].path` patterns in config |
| 3 | Git remote org/owner rules | **0.85** | `rules[].remote_org` matches in config |
| 4 | Git remote org → direct login | **0.6** | Org name matches a known account login |
| 5 | Ecosystem file hints | **0.5** | CODEOWNERS, package.json, go.mod, Cargo.toml, FUNDING.yml |
| 6 | Per-host default | **0.3** | `hosts[host].default_account` in config |
| 7 | Global default | **0.2** | `default_account` in config |

### How Each Signal Works

**`.gh-user` file (1.0):** Walks up from the current directory to find the nearest `.git/` directory (the repo root), then checks for a `.gh-user` file. The file contents are a label or login name.

**Directory path rules (0.9):** The current working directory is matched against glob patterns in `rules[].path`. Patterns support `~` expansion and `**` recursive wildcards. First matching rule wins.

**Git remote org rules (0.85):** Runs `git remote get-url origin`, parses the URL (supports HTTPS, SSH shorthand `git@`, and `ssh://`), extracts the org/owner, and matches it against `rules[].remote_org`. Optionally scoped to a specific `host`.

**Git remote direct match (0.6):** If no remote org rule matches, the extracted org/owner is checked against the `accounts` map and known logins for a direct name match.

**Ecosystem files (0.5):** Scans the repo root for project files that hint at ownership:
- `CODEOWNERS` / `.github/CODEOWNERS` / `docs/CODEOWNERS` → `@org/` team patterns
- `package.json` → npm `@scope` in the package name
- `go.mod` → `module github.com/<org>/...` path
- `Cargo.toml` → `repository` URL org
- `.github/FUNDING.yml` → `github:` usernames

**Per-host default (0.3):** If the target host has a `default_account` configured under `hosts`, it's used as a low-confidence fallback.

**Global default (0.2):** The `default_account` at the top level of the config is the lowest-priority fallback.

### Undetermined Behavior

When no signal fires (or all resolve to `None`), the `behavior.on_undetermined` setting controls what happens:

- **`prompt`** — Show an interactive arrow-key account picker in the terminal
- **`fallback-default`** — Silently use the `default_account`
- **`skip`** — Run `gh` without switching accounts

---

## VS Code Extension

The `vscode-extension/` directory contains a VS Code extension that brings `ghx` intelligence into your editor.

### Installation

```bash
cd vscode-extension
npm install
npm run compile
# Then install via VS Code: Extensions → Install from VSIX
```

### Features

#### `@ghx` Copilot Chat Participant

Talk to ghx in Copilot Chat using natural language:

| Command | Description |
|---------|-------------|
| `@ghx /status` | Show all accounts, active status, and inference signals in a table |
| `@ghx /why` | LLM-powered explanation of why an account was selected |
| `@ghx /switch <account>` | Switch to a named account (by label or login) |
| `@ghx /setup` | AI-assisted configuration generation based on your workspace |
| `@ghx <question>` | Free-form question answered by the Copilot LLM with full context |

#### Status Bar

The status bar shows the active GitHub account. It:
- Displays the account label (or login) with a person icon
- Shows a **warning icon** with orange background when the active account doesn't match what the inference engine recommends
- Refreshes every 30 seconds to catch external `gh auth switch` commands
- Clicking opens the Quick Pick account switcher

#### Auto-Switch on Workspace Open

When you open a workspace, the extension automatically:
1. Runs the inference engine against the workspace path
2. Compares the result to the currently active `gh` account
3. Switches if they differ, showing an info notification

This can be disabled in settings: `ghx.autoSwitch: false`.

### Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `ghx.autoSwitch` | `true` | Automatically switch accounts when opening a workspace |
| `ghx.showStatusBar` | `true` | Show the account indicator in the status bar |
| `ghx.configPath` | `~/.config/ghx/config.yml` | Override the config file location |

### Extension Commands

| Command | Title |
|---------|-------|
| `ghx.switchAccount` | Switch GitHub account (Quick Pick) |
| `ghx.showStatus` | Open `@ghx /status` in Copilot Chat |
| `ghx.openConfig` | Open (or create) the ghx config file |

### How the Bridge Works

The VS Code extension does **not** require the Python CLI to be installed. It reimplements the core logic in TypeScript via `GhxBridge`:

- **Account discovery:** Calls `gh auth status --json hosts` (with text fallback) using `child_process`
- **Account switching:** Calls `gh auth switch --hostname <host> --user <login>`
- **Config loading:** Reads and parses `~/.config/ghx/config.yml` using the `yaml` npm package
- **Inference engine:** Reimplements the same signal priority chain (`.gh-user`, dir rules, git remote, ecosystem files, host/global defaults) in TypeScript
- **Workspace context:** Gathers git remote, project files, config, and account state to feed to the Copilot LLM for `/why` and `/setup` commands

---

## Shell Completions

Tab completions are provided for Bash, Zsh, and Fish in the `completions/` directory.

### Zsh

```bash
# Copy to your fpath, or source directly
cp completions/ghx.zsh ~/.zsh/completions/_ghx
# Add to .zshrc:
fpath=(~/.zsh/completions $fpath)
autoload -Uz compinit && compinit
```

### Bash

```bash
# Source in your .bashrc
source /path/to/completions/ghx.bash

# Or copy to the system completions directory
cp completions/ghx.bash /etc/bash_completion.d/ghx
```

### Fish

```bash
cp completions/ghx.fish ~/.config/fish/completions/ghx.fish
```

All completions:
- Complete `ghx` subcommands (`status`, `init`) and flags (`--gh-user`, `--gh-debug`, etc.)
- Auto-complete account labels from your config when using `--gh-user`
- Delegate to `gh`'s own completions for pass-through subcommands

---

## Architecture

```
GitHub-autoswitch/
├── src/ghx/                  # Python CLI package
│   ├── __init__.py           # Version
│   ├── cli.py                # Entry point, arg parsing, main flow
│   ├── config.py             # YAML config loading and validation
│   ├── gh.py                 # gh CLI interaction (accounts, switch, delegate)
│   ├── inference.py          # Signal evaluation engine
│   ├── picker.py             # Interactive terminal account picker
│   └── status.py             # `ghx status` display
├── tests/                    # pytest test suite
│   ├── conftest.py           # Shared fixtures
│   ├── test_config.py        # Config loading tests
│   ├── test_gh.py            # gh CLI interaction tests
│   └── test_inference.py     # Inference engine tests
├── completions/              # Shell tab-completion scripts
│   ├── ghx.bash
│   ├── ghx.fish
│   └── ghx.zsh
├── vscode-extension/         # VS Code extension (TypeScript)
│   ├── package.json          # Extension manifest
│   ├── tsconfig.json         # TypeScript config
│   └── src/
│       ├── extension.ts      # Activation, commands, auto-switch
│       ├── chatParticipant.ts # @ghx Copilot Chat participant
│       ├── ghxBridge.ts      # gh CLI bridge (TypeScript reimplementation)
│       └── statusBar.ts      # Status bar indicator
├── pyproject.toml            # Python build config (hatchling)
├── PRD.md                    # Product requirements document
├── README.md                 # This file
└── SECURITY.md               # Security policy
```

### Key Design Decisions

- **`os.execvp` for delegation:** After switching accounts, `ghx` replaces its own process with `gh`. This means `gh` inherits the terminal, environment, and signal handlers exactly as if the user ran `gh` directly. No output buffering, no exit code translation.
- **Confidence-based inference:** Rather than a rigid priority chain, each signal produces a confidence score. This makes it easy to add new signal types and lets the user see *why* a decision was made.
- **Independent VS Code implementation:** The extension doesn't shell out to the Python CLI. It reimplements the inference engine in TypeScript so it works even without Python installed.
- **Graceful degradation:** `gh auth status --json` is tried first; if it fails (older `gh` versions), text parsing kicks in. Missing config files produce empty defaults, not errors.

---

## Development

### Setup

```bash
git clone https://github.com/msfttoler/GitHub-autoswitch.git
cd GitHub-autoswitch
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
pytest -v               # verbose
pytest --tb=short       # shorter tracebacks
```

### Run the CLI in debug mode

```bash
ghx --gh-debug status
ghx --gh-debug pr list
```

### Override the `gh` binary (for testing)

```bash
GH_BIN=/path/to/custom/gh ghx status
```

### VS Code Extension Development

```bash
cd vscode-extension
npm install
npm run compile
# Press F5 in VS Code to launch the Extension Development Host
```

---

## Troubleshooting

### "No accounts found"

Make sure you're logged in with `gh`:
```bash
gh auth status
gh auth login   # if needed
```

### Config file not found

Run `ghx init` to create one, or manually create `~/.config/ghx/config.yml`.

### Account not switching

1. Run `ghx --gh-debug <command>` to see which signals fired
2. Check `ghx status` to see the full inference breakdown
3. Ensure your config labels match real `gh` login usernames

### VS Code extension not detecting accounts

Make sure `gh` is in your PATH and accessible from VS Code's integrated terminal.

---

## Security

See [SECURITY.md](SECURITY.md) for our security policy, including how to report vulnerabilities.

---

## License

[MIT](LICENSE)

## How Inference Works

`ghx` evaluates multiple signals in priority order and picks the highest-confidence match:

| Priority | Signal | Confidence | Source |
|---|---|---|---|
| 1 | `.gh-user` file in repo root | 1.0 | Per-repo override |
| 2 | Directory path rules | 0.9 | Config `rules[].path` |
| 3 | Git remote org rules | 0.85 | Config `rules[].remote_org` |
| 4 | Git remote org → direct login match | 0.6 | Org name = account login |
| 5 | Ecosystem files (CODEOWNERS, package.json, etc.) | 0.5 | File content analysis |
| 6 | Per-host default | 0.3 | Config `hosts[].default_account` |
| 7 | Global default | 0.2 | Config `default_account` |

### Per-Repo Override

Drop a `.gh-user` file in any repo root:

```bash
echo "work" > .gh-user   # Uses your "work" account label
```

### Ecosystem File Detection

`ghx` scans your repo for org/ownership hints:

- **CODEOWNERS** — `@my-company/team-name` patterns → maps `my-company` to an account
- **package.json** — `@scope/package-name` → maps `scope` to an account
- **go.mod** — `module github.com/org/module` → maps `org` to an account
- **Cargo.toml** — `repository = "https://github.com/org/crate"` → maps `org`
- **.github/FUNDING.yml** — `github: username` → maps `username`

---

## CLI Reference

### Wrapper Flags

These are processed by `ghx` and not passed to `gh`:

```
--gh-user <label>    Force a specific account (label or login)
--gh-no-auto         Skip auto-detection, pass through to gh directly
--gh-debug           Print inference signals and subprocess commands
--gh-config <path>   Override config file location
```

### Built-in Commands

```bash
ghx status           # Show accounts, active account, and inference signals
ghx init             # Interactive setup wizard
```

### Examples

```bash
ghx pr create                    # Auto-switch + create PR
ghx --gh-user work pr create     # Force work account
ghx --gh-no-auto pr list         # No auto-switch
ghx --gh-debug issue list        # See what ghx is deciding
ghx status                       # Full status report
```

---

## VS Code Extension

### Installation

```bash
cd vscode-extension
npm install
npm run compile
# Then install via VS Code: Extensions → Install from VSIX
npx @vscode/vsce package
```

### Chat Participant

In Copilot Chat, type `@ghx` to interact:

```
@ghx /status                          → Account overview with inference signals
@ghx /why                             → LLM explains why this account was chosen
@ghx /switch work                     → Switch to your work account
@ghx /setup                           → AI generates config based on your workspace
@ghx which account should I use here? → Free-form question answered by LLM
```

### Status Bar

Shows `👤 work` in the status bar. Click to switch. Shows a warning `⚠️ work` when the active account doesn't match what inference suggests.

### Settings

| Setting | Default | Description |
|---|---|---|
| `ghx.autoSwitch` | `true` | Auto-switch account on workspace open |
| `ghx.configPath` | `""` | Override config file path |
| `ghx.showStatusBar` | `true` | Show account in status bar |

---

## Shell Completions

### Zsh

```bash
# Add to .zshrc
fpath=(/path/to/GitHub-autoswitch/completions $fpath)
autoload -Uz compinit && compinit
```

### Bash

```bash
# Add to .bashrc
source /path/to/GitHub-autoswitch/completions/ghx.bash
```

### Fish

```bash
# Copy to fish completions
cp completions/ghx.fish ~/.config/fish/completions/
```

---

## Project Structure

```
GitHub-autoswitch/
├── pyproject.toml             # Python packaging (pip install .)
├── src/ghx/
│   ├── cli.py                 # Main CLI entry point
│   ├── config.py              # Config loading & validation
│   ├── gh.py                  # gh CLI interaction
│   ├── inference.py           # Signal evaluation engine
│   ├── picker.py              # Interactive account picker
│   └── status.py              # Status display
├── tests/                     # pytest test suite
├── completions/               # Shell completions (zsh/bash/fish)
└── vscode-extension/
    ├── package.json            # Extension manifest
    └── src/
        ├── extension.ts        # Entry point + commands
        ├── chatParticipant.ts  # @ghx Copilot Chat participant
        ├── ghxBridge.ts        # gh CLI + config bridge
        └── statusBar.ts        # Status bar integration
```

---

## Development

```bash
# Python CLI
pip install -e ".[dev]"
pytest

# VS Code Extension
cd vscode-extension
npm install
npm run watch    # Compile in watch mode
# Press F5 in VS Code to launch Extension Development Host
```

## License

MIT
