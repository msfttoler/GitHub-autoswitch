# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in `ghx`, please report it responsibly. **Do not open a public GitHub issue.**

### How to Report

1. **Email:** Send a description to the repository maintainer via the contact information on their GitHub profile.
2. **GitHub Security Advisories:** Use the [private vulnerability reporting](https://github.com/msfttoler/GitHub-autoswitch/security/advisories/new) feature to submit a confidential report directly on GitHub.

### What to Include

- A description of the vulnerability and its potential impact.
- Steps to reproduce the issue, or a proof-of-concept.
- The version of `ghx` affected.
- Any suggested fix, if you have one.

### Response Timeline

- **Acknowledgment:** within 5 business days.
- **Assessment and fix:** best effort, typically within 30 days for confirmed issues.
- **Disclosure:** coordinated with the reporter once a fix is available.

---

## Security Model

### What `ghx` Does

`ghx` is a CLI wrapper that:

1. Reads a user-owned YAML configuration file (`~/.config/ghx/config.yml`).
2. Inspects the local filesystem (current directory, `.gh-user` files, project files).
3. Runs `git` subcommands to read remote URLs.
4. Runs `gh auth status` and `gh auth switch` to manage GitHub CLI authentication.
5. Replaces its own process with `gh` via `os.execvp` to execute the user's original command.

### Trust Boundaries

| Boundary | Trust Level | Notes |
|----------|-------------|-------|
| Config file (`config.yml`) | **User-owned** | Read from `~/.config/ghx/`. Only the file owner should have write access. |
| `.gh-user` files | **Repo-scoped** | Read from the repository working tree. Treat with the same trust as any file in a cloned repo. |
| `gh` CLI | **Trusted dependency** | `ghx` delegates all GitHub API interactions to `gh`. It never contacts GitHub directly. |
| `git` CLI | **Trusted dependency** | Used only to read `remote get-url origin`. No writes. |
| Ecosystem files | **Repo-scoped** | `package.json`, `go.mod`, `Cargo.toml`, `CODEOWNERS`, `FUNDING.yml` are read for inference hints. Parsed defensively. |
| VS Code extension | **Trusted dependency** | Reimplements inference in TypeScript. Calls `gh` and `git` via `child_process`. |

### What `ghx` Does NOT Do

- **No network access.** `ghx` itself never opens network connections. All GitHub API calls are made by `gh` after `ghx` hands off control.
- **No credential storage.** `ghx` does not read, store, or transmit authentication tokens. Credential management is entirely handled by `gh`.
- **No elevated privileges.** `ghx` runs with the same permissions as the invoking user. It does not require `sudo` or any special capabilities.
- **No code execution from config.** The YAML config is parsed with `yaml.safe_load()` (Python) or the `yaml` npm package's `YAML.parse()` (TypeScript), neither of which execute arbitrary code.
- **No shell expansion of config values.** Directory patterns in rules are matched with `fnmatch` and string prefix comparison — not passed through a shell.

---

## Potential Risks and Mitigations

### 1. Malicious `.gh-user` or Ecosystem Files in Cloned Repos

**Risk:** A cloned repository could contain a `.gh-user` file or crafted `package.json`/`CODEOWNERS` that attempts to trick `ghx` into switching to an unintended account.

**Mitigation:**
- `.gh-user` values are resolved against the `accounts` map and known `gh` logins. Arbitrary strings that don't match a configured account or authenticated login are ignored.
- Ecosystem file parsing uses defensive JSON/text parsing and only extracts org/scope names — no code is executed.
- The impact is limited to switching between accounts the user has already authenticated with `gh auth login`. No new access is granted.

**Recommendation:** Review `.gh-user` files in untrusted repositories before running `ghx`. Add `.gh-user` to your global `.gitignore` to prevent accidental commits.

### 2. Config File Tampering

**Risk:** If another user or process can write to `~/.config/ghx/config.yml`, they could redirect account switching.

**Mitigation:**
- The config directory inherits standard Unix file permissions. Only the config file owner should have write access.
- `ghx` does not create the config directory with world-writable permissions.

**Recommendation:** Ensure `~/.config/ghx/` has permissions `700` or `755`:
```bash
chmod 700 ~/.config/ghx
chmod 600 ~/.config/ghx/config.yml
```

### 3. Subprocess Invocations

**Risk:** `ghx` runs `gh` and `git` as subprocesses. If the `PATH` is manipulated, a malicious binary could be executed instead.

**Mitigation:**
- `ghx` uses `os.execvp` and `subprocess.run` with explicit argument lists (never shell strings), preventing shell injection.
- The `gh` binary path can be overridden via the `GH_BIN` environment variable for testing, but this is under user control.
- `git` is invoked via argument list, not through a shell.

**Recommendation:** Ensure your `PATH` is not writable by untrusted users. Avoid running `ghx` in environments where `PATH` may be compromised.

### 4. YAML Parsing

**Risk:** YAML deserialization can be dangerous if using unsafe loaders.

**Mitigation:**
- Python: Uses `yaml.safe_load()`, which only constructs basic Python types (strings, numbers, lists, dicts). No arbitrary object instantiation.
- TypeScript: Uses the `yaml` npm package's `YAML.parse()`, which produces plain JavaScript objects.

### 5. Information Exposure in Debug Mode

**Risk:** `--gh-debug` prints internal decisions including account logins and directory paths to stderr.

**Mitigation:**
- Debug output goes to stderr, not stdout, so it doesn't contaminate piped output.
- Debug mode is opt-in and off by default.

**Recommendation:** Do not enable `--gh-debug` in shared CI/CD logs where account information should remain private.

### 6. VS Code Extension — Copilot LLM Context

**Risk:** The `/why` and `/setup` chat commands send workspace context (git remote URLs, file contents, account names, config) to the Copilot LLM.

**Mitigation:**
- This data follows the same data handling policies as GitHub Copilot Chat.
- File contents are truncated to 500 characters to minimize exposure.
- The extension only sends data that is already visible to the user in their workspace.

**Recommendation:** Review the [GitHub Copilot privacy documentation](https://docs.github.com/en/copilot/overview-of-github-copilot/about-github-copilot-individual#about-privacy) if you have concerns about workspace data being sent to LLM APIs.

---

## Dependency Security

### Python CLI

| Dependency | Purpose | Notes |
|------------|---------|-------|
| `pyyaml` ≥ 6.0 | Config file parsing | Uses `safe_load()` only |

Dev dependencies (`pytest`, `pytest-mock`) are not included in production installs.

### VS Code Extension

| Dependency | Purpose | Notes |
|------------|---------|-------|
| `yaml` (npm) | Config file parsing | Uses `YAML.parse()` (safe by default) |
| `vscode` API | Extension host integration | Provided by VS Code |

### External CLI Dependencies

| Tool | Usage | Trust |
|------|-------|-------|
| `gh` (GitHub CLI) | Account management, command delegation | User-installed, trusted |
| `git` | Remote URL reading | User-installed, trusted |

---

## Best Practices for Users

1. **Keep `gh` updated** to get the latest security fixes.
2. **Protect your config file** — ensure only you have write access to `~/.config/ghx/`.
3. **Review `.gh-user` files** in repositories you clone from untrusted sources.
4. **Don't commit `.gh-user` files** — add to `.gitignore` to prevent leaking account preferences.
5. **Audit your accounts** — regularly run `ghx status` to verify which accounts are authenticated and active.
6. **Use `--gh-no-auto` in scripts** if you want deterministic behavior without inference.
