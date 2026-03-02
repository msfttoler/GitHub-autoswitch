/**
 * extension.ts — Main entry point for the ghx VS Code extension.
 *
 * Activates:
 *   - @ghx Copilot Chat Participant
 *   - Status bar account indicator
 *   - Commands for switching accounts and managing config
 */

import * as fs from "fs";
import * as vscode from "vscode";
import { registerChatParticipant } from "./chatParticipant";
import { GhxBridge } from "./ghxBridge";
import { GhxStatusBar } from "./statusBar";

export function activate(context: vscode.ExtensionContext): void {
  const bridge = new GhxBridge();

  // ── Chat Participant ───────────────────────────────────────────
  registerChatParticipant(context, bridge);

  // ── Status Bar ─────────────────────────────────────────────────
  const statusBar = new GhxStatusBar(bridge);
  statusBar.activate(context);

  // ── Commands ───────────────────────────────────────────────────

  context.subscriptions.push(
    vscode.commands.registerCommand("ghx.switchAccount", async () => {
      const accounts = await bridge.getAccounts();
      if (accounts.length === 0) {
        vscode.window.showWarningMessage(
          "No GitHub accounts found. Run `gh auth login` first."
        );
        return;
      }

      const config = bridge.loadConfig();
      const items = accounts.map((acct) => {
        const label = config
          ? Object.entries(config.accounts).find(
              ([, login]) => login === acct.login
            )?.[0]
          : undefined;
        const activeTag = acct.active ? " $(check)" : "";
        return {
          label: `${label ? `${label} — ` : ""}${acct.login}${activeTag}`,
          description: acct.host,
          login: acct.login,
          host: acct.host,
        };
      });

      const picked = await vscode.window.showQuickPick(items, {
        placeHolder: "Select GitHub account to switch to",
        title: "ghx: Switch Account",
      });

      if (picked) {
        const result = await bridge.switchAccount(
          picked.login,
          picked.host
        );
        if (result.success) {
          vscode.window.showInformationMessage(`ghx: ${result.message}`);
          statusBar.refresh();
        } else {
          vscode.window.showErrorMessage(`ghx: ${result.message}`);
        }
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("ghx.showStatus", async () => {
      // Open the chat with @ghx /status
      vscode.commands.executeCommand("workbench.action.chat.open", {
        query: "@ghx /status",
      });
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("ghx.openConfig", async () => {
      const configPath = bridge.getConfigPath();

      if (!fs.existsSync(configPath)) {
        const action = await vscode.window.showInformationMessage(
          `ghx config not found at ${configPath}`,
          "Create Default Config",
          "Cancel"
        );

        if (action === "Create Default Config") {
          // Create the config directory and write example config
          const dir = configPath.substring(
            0,
            configPath.lastIndexOf("/")
          );
          fs.mkdirSync(dir, { recursive: true });

          // Use the Python module's example config format
          const exampleConfig = `# ghx configuration
# See: https://github.com/msfttoler/GitHub-autoswitch

accounts:
  work: your-work-login
  personal: your-personal-login

hosts:
  github.com:
    default_account: personal

rules:
  - path: "~/code/work/**"
    account: work
  - path: "~/code/personal/**"
    account: personal

default_account: personal

behavior:
  on_switch_error: warn-and-continue
  on_undetermined: prompt
`;
          fs.writeFileSync(configPath, exampleConfig, "utf-8");
        } else {
          return;
        }
      }

      const doc = await vscode.workspace.openTextDocument(configPath);
      await vscode.window.showTextDocument(doc);
    })
  );

  // ── Auto-switch on workspace open ──────────────────────────────
  const autoSwitch = vscode.workspace
    .getConfiguration("ghx")
    .get<boolean>("autoSwitch", true);

  if (autoSwitch) {
    performAutoSwitch(bridge, statusBar);
  }
}

async function performAutoSwitch(
  bridge: GhxBridge,
  statusBar: GhxStatusBar
): Promise<void> {
  const workspacePath =
    vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!workspacePath) {
    return;
  }

  try {
    const result = await bridge.inferAccount(workspacePath);
    if (!result.login) {
      return;
    }

    const activeLogin = await bridge.getActiveLogin();
    if (activeLogin === result.login) {
      return;
    }

    const switchResult = await bridge.switchAccount(result.login);
    if (switchResult.success) {
      vscode.window.showInformationMessage(
        `ghx: ${switchResult.message} (${result.signals[0]?.detail || "auto-detected"})`
      );
      statusBar.refresh();
    }
  } catch {
    // Silent failure on auto-switch — don't annoy the user
  }
}

export function deactivate(): void {
  // Cleanup is handled by context.subscriptions
}
