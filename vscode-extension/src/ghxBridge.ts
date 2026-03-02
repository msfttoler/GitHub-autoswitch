/**
 * ghxBridge.ts — Bridge between the VS Code extension and
 * the gh CLI / ghx config. Provides account discovery, switching,
 * config loading, and workspace inference without requiring the
 * Python CLI to be installed.
 */

import * as cp from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

// We use the `yaml` npm package for config parsing
import YAML from "yaml";

// ── Types ────────────────────────────────────────────────────────────

export interface GhAccount {
  host: string;
  login: string;
  active: boolean;
}

export interface GhxRule {
  path?: string;
  remote_org?: string;
  account: string;
  host?: string;
}

export interface GhxConfig {
  accounts: Record<string, string>;
  hosts: Record<string, { default_account?: string }>;
  rules: GhxRule[];
  default_account?: string;
  behavior: {
    on_switch_error: string;
    on_undetermined: string;
  };
}

export interface InferenceSignal {
  source: string;
  accountLabel: string;
  detail: string;
  confidence: number;
}

export interface InferenceResult {
  login: string | undefined;
  host: string;
  signals: InferenceSignal[];
  allSignals: InferenceSignal[];
}

// ── Bridge Class ─────────────────────────────────────────────────────

export class GhxBridge {
  private ghBin: string;
  private configPath: string;

  constructor() {
    this.ghBin = process.env.GH_BIN || "gh";
    const configOverride = vscode.workspace
      .getConfiguration("ghx")
      .get<string>("configPath");
    this.configPath =
      configOverride ||
      path.join(os.homedir(), ".config", "ghx", "config.yml");
  }

  // ── Account Discovery ────────────────────────────────────────────

  async getAccounts(): Promise<GhAccount[]> {
    // Try JSON output first
    try {
      const stdout = await this.exec([
        "auth",
        "status",
        "--json",
        "hosts",
      ]);
      return this.parseJsonStatus(stdout);
    } catch {
      // Fall back to text parsing
    }

    try {
      const stdout = await this.exec(["auth", "status"]);
      return this.parseTextStatus(stdout);
    } catch {
      return [];
    }
  }

  async getActiveLogin(host: string = "github.com"): Promise<string | undefined> {
    const accounts = await this.getAccounts();
    return accounts.find((a) => a.host === host && a.active)?.login;
  }

  // ── Account Switching ────────────────────────────────────────────

  async switchAccount(
    login: string,
    host: string = "github.com"
  ): Promise<{ success: boolean; message: string }> {
    try {
      await this.exec([
        "auth",
        "switch",
        "--hostname",
        host,
        "--user",
        login,
      ]);
      return { success: true, message: `Switched to ${login} on ${host}` };
    } catch (err) {
      return {
        success: false,
        message: `Switch failed: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  }

  // ── Config Loading ───────────────────────────────────────────────

  loadConfig(): GhxConfig | null {
    if (!fs.existsSync(this.configPath)) {
      return null;
    }

    try {
      const content = fs.readFileSync(this.configPath, "utf-8");
      const raw = YAML.parse(content);
      if (!raw || typeof raw !== "object") {
        return null;
      }

      return {
        accounts: raw.accounts || {},
        hosts: raw.hosts || {},
        rules: (raw.rules || []).map((r: Record<string, unknown>) => ({
          path: r.path as string | undefined,
          remote_org: r.remote_org as string | undefined,
          account: (r.account as string) || "",
          host: r.host as string | undefined,
        })),
        default_account: raw.default_account,
        behavior: {
          on_switch_error:
            raw.behavior?.on_switch_error || "warn-and-continue",
          on_undetermined: raw.behavior?.on_undetermined || "prompt",
        },
      };
    } catch {
      return null;
    }
  }

  getConfigPath(): string {
    return this.configPath;
  }

  // ── Workspace Inference ──────────────────────────────────────────

  async inferAccount(
    workspacePath: string,
    host: string = "github.com"
  ): Promise<InferenceResult> {
    const config = this.loadConfig();
    const accounts = await this.getAccounts();
    const knownLogins = accounts.map((a) => a.login);

    const result: InferenceResult = {
      login: undefined,
      host,
      signals: [],
      allSignals: [],
    };

    if (!config) {
      return result;
    }

    const signals: InferenceSignal[] = [];

    // 1. .gh-user file
    const ghUserSignal = this.checkRepoOverride(
      workspacePath,
      config,
      knownLogins
    );
    if (ghUserSignal) {
      signals.push(ghUserSignal);
    }

    // 2. Directory rules
    const dirSignal = this.checkDirRules(
      workspacePath,
      config,
      knownLogins
    );
    if (dirSignal) {
      signals.push(dirSignal);
    }

    // 3. Git remote
    const remoteSignals = await this.checkGitRemote(
      workspacePath,
      config,
      knownLogins,
      host
    );
    signals.push(...remoteSignals);

    // 4. Ecosystem files
    const ecoSignals = this.checkEcosystemFiles(
      workspacePath,
      config,
      knownLogins
    );
    signals.push(...ecoSignals);

    // 5. Host default
    const hostConfig = config.hosts[host];
    if (hostConfig?.default_account) {
      const login = this.resolveLabel(
        hostConfig.default_account,
        config,
        knownLogins
      );
      if (login) {
        signals.push({
          source: "host-default",
          accountLabel: hostConfig.default_account,
          detail: `Host default for ${host}: ${hostConfig.default_account}`,
          confidence: 0.3,
        });
      }
    }

    // 6. Global default
    if (config.default_account) {
      const login = this.resolveLabel(
        config.default_account,
        config,
        knownLogins
      );
      if (login) {
        signals.push({
          source: "global-default",
          accountLabel: config.default_account,
          detail: `Global default: ${config.default_account}`,
          confidence: 0.2,
        });
      }
    }

    result.allSignals = signals;

    if (signals.length > 0) {
      const best = signals.reduce((a, b) =>
        a.confidence >= b.confidence ? a : b
      );
      result.login = this.resolveLabel(
        best.accountLabel,
        config,
        knownLogins
      );
      result.signals = signals.filter(
        (s) => s.confidence === best.confidence
      );
    }

    return result;
  }

  // ── Workspace Context (for Copilot LLM) ──────────────────────────

  async gatherWorkspaceContext(
    workspacePath: string
  ): Promise<string> {
    const parts: string[] = [];

    // Git remote
    try {
      const remote = await this.execInDir(
        ["git", "remote", "get-url", "origin"],
        workspacePath
      );
      parts.push(`Git remote origin: ${remote.trim()}`);
    } catch {
      parts.push("Git remote: not available");
    }

    // Check for key files
    const filesToCheck = [
      "CODEOWNERS",
      ".github/CODEOWNERS",
      "package.json",
      "go.mod",
      "Cargo.toml",
      ".github/FUNDING.yml",
      ".gh-user",
    ];

    for (const f of filesToCheck) {
      const fullPath = path.join(workspacePath, f);
      if (fs.existsSync(fullPath)) {
        try {
          const content = fs.readFileSync(fullPath, "utf-8");
          // Limit content to avoid token bloat
          const truncated =
            content.length > 500
              ? content.substring(0, 500) + "\n...(truncated)"
              : content;
          parts.push(`File ${f}:\n${truncated}`);
        } catch {
          parts.push(`File ${f}: exists but unreadable`);
        }
      }
    }

    // Current config
    const config = this.loadConfig();
    if (config) {
      parts.push(
        `ghx config accounts: ${JSON.stringify(config.accounts)}`
      );
      parts.push(`ghx config rules: ${JSON.stringify(config.rules)}`);
      parts.push(`ghx default_account: ${config.default_account || "(none)"}`);
    } else {
      parts.push("ghx config: not found");
    }

    // Current accounts
    const accounts = await this.getAccounts();
    parts.push(
      `gh accounts: ${accounts.map((a) => `${a.login}@${a.host}${a.active ? " (active)" : ""}`).join(", ") || "(none)"}`
    );

    return parts.join("\n\n");
  }

  // ── Private Helpers ──────────────────────────────────────────────

  private resolveLabel(
    labelOrLogin: string,
    config: GhxConfig,
    knownLogins: string[]
  ): string | undefined {
    if (labelOrLogin in config.accounts) {
      return config.accounts[labelOrLogin];
    }
    if (knownLogins.includes(labelOrLogin)) {
      return labelOrLogin;
    }
    if (Object.values(config.accounts).includes(labelOrLogin)) {
      return labelOrLogin;
    }
    return undefined;
  }

  private checkRepoOverride(
    workspacePath: string,
    config: GhxConfig,
    knownLogins: string[]
  ): InferenceSignal | null {
    const ghUserPath = path.join(workspacePath, ".gh-user");
    if (!fs.existsSync(ghUserPath)) {
      return null;
    }

    const label = fs.readFileSync(ghUserPath, "utf-8").trim();
    if (!label) {
      return null;
    }

    const login = this.resolveLabel(label, config, knownLogins);
    if (login) {
      return {
        source: "repo-override",
        accountLabel: label,
        detail: `.gh-user file specifies: ${label}`,
        confidence: 1.0,
      };
    }
    return null;
  }

  private checkDirRules(
    workspacePath: string,
    config: GhxConfig,
    knownLogins: string[]
  ): InferenceSignal | null {
    const resolvedPath = path.resolve(workspacePath);

    for (const rule of config.rules) {
      if (!rule.path || !rule.account) {
        continue;
      }

      let pattern = rule.path.replace(/^~/, os.homedir());

      if (pattern.endsWith("/**")) {
        const prefix = pattern.slice(0, -3);
        if (
          resolvedPath.startsWith(prefix) ||
          resolvedPath === prefix.replace(/\/$/, "")
        ) {
          const login = this.resolveLabel(
            rule.account,
            config,
            knownLogins
          );
          if (login) {
            return {
              source: "dir-rule",
              accountLabel: rule.account,
              detail: `Directory matches rule: ${rule.path}`,
              confidence: 0.9,
            };
          }
        }
      }
    }
    return null;
  }

  private async checkGitRemote(
    workspacePath: string,
    config: GhxConfig,
    knownLogins: string[],
    targetHost: string
  ): Promise<InferenceSignal[]> {
    const signals: InferenceSignal[] = [];

    let remoteUrl: string;
    try {
      remoteUrl = (
        await this.execInDir(
          ["git", "remote", "get-url", "origin"],
          workspacePath
        )
      ).trim();
    } catch {
      return signals;
    }

    const parsed = this.parseRemoteUrl(remoteUrl);
    if (!parsed) {
      return signals;
    }

    const { org } = parsed;

    // Check remote_org rules
    for (const rule of config.rules) {
      if (!rule.remote_org || !rule.account) {
        continue;
      }
      const ruleHost = rule.host || "github.com";
      if (
        rule.remote_org.toLowerCase() === org.toLowerCase() &&
        (parsed.host || "github.com") === ruleHost
      ) {
        const login = this.resolveLabel(
          rule.account,
          config,
          knownLogins
        );
        if (login) {
          signals.push({
            source: "remote-org",
            accountLabel: rule.account,
            detail: `Git remote org '${org}' matches rule → ${rule.account}`,
            confidence: 0.85,
          });
        }
      }
    }

    // Direct match
    if (signals.length === 0) {
      const login = this.resolveLabel(org, config, knownLogins);
      if (login) {
        signals.push({
          source: "remote-org-direct",
          accountLabel: org,
          detail: `Git remote org '${org}' matches account login directly`,
          confidence: 0.6,
        });
      }
    }

    return signals;
  }

  private checkEcosystemFiles(
    workspacePath: string,
    config: GhxConfig,
    knownLogins: string[]
  ): InferenceSignal[] {
    const signals: InferenceSignal[] = [];

    // package.json scope
    const pkgJsonPath = path.join(workspacePath, "package.json");
    if (fs.existsSync(pkgJsonPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(pkgJsonPath, "utf-8"));
        const name: string = data.name || "";
        if (name.startsWith("@")) {
          const scope = name.split("/")[0].slice(1);
          const login = this.resolveLabel(scope, config, knownLogins);
          if (login) {
            signals.push({
              source: "package-json",
              accountLabel: scope,
              detail: `package.json scope @${scope}`,
              confidence: 0.5,
            });
          }
        }
      } catch {
        /* ignore parse errors */
      }
    }

    // CODEOWNERS
    for (const codeownersRel of [
      "CODEOWNERS",
      ".github/CODEOWNERS",
      "docs/CODEOWNERS",
    ]) {
      const coPath = path.join(workspacePath, codeownersRel);
      if (fs.existsSync(coPath)) {
        try {
          const content = fs.readFileSync(coPath, "utf-8");
          const orgMatches = content.match(/@([a-zA-Z0-9_-]+)\//g);
          if (orgMatches) {
            const orgs = new Set(
              orgMatches.map((m: string) => m.slice(1, -1))
            );
            for (const org of orgs) {
              const login = this.resolveLabel(org, config, knownLogins);
              if (login) {
                signals.push({
                  source: "codeowners",
                  accountLabel: org,
                  detail: `CODEOWNERS references @${org}/ teams`,
                  confidence: 0.5,
                });
              }
            }
          }
        } catch {
          /* ignore */
        }
        break;
      }
    }

    return signals;
  }

  private parseRemoteUrl(
    url: string
  ): { host: string; org: string; repo: string } | null {
    // HTTPS
    let m = url.match(/^https?:\/\/([^/]+)\/([^/]+)\/([^/]+?)(?:\.git)?$/);
    if (m) {
      return { host: m[1], org: m[2], repo: m[3] };
    }

    // SSH shorthand
    m = url.match(/^git@([^:]+):([^/]+)\/([^/]+?)(?:\.git)?$/);
    if (m) {
      return { host: m[1], org: m[2], repo: m[3] };
    }

    // SSH URL
    m = url.match(/^ssh:\/\/[^@]+@([^/]+)\/([^/]+)\/([^/]+?)(?:\.git)?$/);
    if (m) {
      return { host: m[1], org: m[2], repo: m[3] };
    }

    return null;
  }

  private parseJsonStatus(stdout: string): GhAccount[] {
    const data = JSON.parse(stdout);
    const accounts: GhAccount[] = [];

    if (typeof data === "object" && data !== null) {
      const hosts = data.hosts || data;
      if (typeof hosts === "object" && !Array.isArray(hosts)) {
        for (const [hostName, hostData] of Object.entries(hosts)) {
          if (Array.isArray(hostData)) {
            for (const entry of hostData) {
              if (
                typeof entry === "object" &&
                entry !== null &&
                (entry as Record<string, unknown>).login
              ) {
                const e = entry as Record<string, unknown>;
                accounts.push({
                  host: hostName,
                  login: e.login as string,
                  active: Boolean(e.active),
                });
              }
            }
          }
        }
      } else if (Array.isArray(hosts)) {
        for (const entry of hosts) {
          if (
            typeof entry === "object" &&
            entry !== null &&
            (entry as Record<string, unknown>).login
          ) {
            const e = entry as Record<string, unknown>;
            accounts.push({
              host: (e.host as string) || "github.com",
              login: e.login as string,
              active: Boolean(e.active),
            });
          }
        }
      }
    }

    return accounts;
  }

  private parseTextStatus(output: string): GhAccount[] {
    const accounts: GhAccount[] = [];
    let currentHost: string | null = null;

    for (const line of output.split("\n")) {
      const stripped = line.trim();

      if (
        stripped &&
        stripped.includes(".") &&
        !stripped.includes(" ") &&
        !stripped.startsWith("✓") &&
        !stripped.startsWith("-") &&
        !stripped.startsWith("X") &&
        !stripped.startsWith("●")
      ) {
        currentHost = stripped;
        continue;
      }

      if (currentHost && stripped.includes("Logged in to")) {
        const parts = stripped.split("account ");
        if (parts.length > 1) {
          const login = parts[1].split(/\s/)[0].replace(/[()]/g, "");
          const active =
            stripped.includes("✓") || stripped.includes("●");
          accounts.push({ host: currentHost, login, active });
        }
      }
    }

    return accounts;
  }

  private exec(args: string[]): Promise<string> {
    return new Promise((resolve, reject) => {
      cp.execFile(
        this.ghBin,
        args,
        { timeout: 10000 },
        (err, stdout, stderr) => {
          if (err) {
            reject(new Error(stderr || err.message));
          } else {
            resolve(stdout);
          }
        }
      );
    });
  }

  private execInDir(cmd: string[], cwd: string): Promise<string> {
    return new Promise((resolve, reject) => {
      cp.execFile(
        cmd[0],
        cmd.slice(1),
        { cwd, timeout: 10000 },
        (err, stdout, stderr) => {
          if (err) {
            reject(new Error(stderr || err.message));
          } else {
            resolve(stdout);
          }
        }
      );
    });
  }
}
