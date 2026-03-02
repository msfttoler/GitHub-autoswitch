/**
 * statusBar.ts — Status bar integration for ghx
 *
 * Shows the currently active GitHub account in the VS Code status bar.
 * Updates automatically when the workspace changes or accounts are switched.
 */

import * as vscode from "vscode";
import { GhxBridge } from "./ghxBridge";

export class GhxStatusBar {
  private statusBarItem: vscode.StatusBarItem;
  private bridge: GhxBridge;
  private refreshTimer: ReturnType<typeof setInterval> | undefined;

  constructor(bridge: GhxBridge) {
    this.bridge = bridge;
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      50
    );
    this.statusBarItem.command = "ghx.switchAccount";
    this.statusBarItem.name = "ghx Account";
  }

  async activate(context: vscode.ExtensionContext): Promise<void> {
    const showStatusBar = vscode.workspace
      .getConfiguration("ghx")
      .get<boolean>("showStatusBar", true);

    if (!showStatusBar) {
      return;
    }

    context.subscriptions.push(this.statusBarItem);

    // Initial update
    await this.refresh();

    // Refresh on workspace folder change
    context.subscriptions.push(
      vscode.workspace.onDidChangeWorkspaceFolders(() => this.refresh())
    );

    // Refresh on config change
    context.subscriptions.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("ghx")) {
          this.refresh();
        }
      })
    );

    // Periodic refresh (every 30s) to catch external `gh auth switch`
    this.refreshTimer = setInterval(() => this.refresh(), 30_000);
    context.subscriptions.push({
      dispose: () => {
        if (this.refreshTimer) {
          clearInterval(this.refreshTimer);
        }
      },
    });

    this.statusBarItem.show();
  }

  async refresh(): Promise<void> {
    const workspacePath =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    try {
      const accounts = await this.bridge.getAccounts();

      if (accounts.length === 0) {
        this.statusBarItem.text = "$(person) No gh accounts";
        this.statusBarItem.tooltip = "Click to set up GitHub CLI accounts";
        return;
      }

      // Get inferred account for workspace
      let inferredLogin: string | undefined;
      let inferReason: string | undefined;

      if (workspacePath) {
        const result = await this.bridge.inferAccount(workspacePath);
        inferredLogin = result.login;
        if (result.signals.length > 0) {
          inferReason = result.signals[0].detail;
        }
      }

      // Find active account
      const activeAccount = accounts.find(
        (a) => a.host === "github.com" && a.active
      );

      const config = this.bridge.loadConfig();
      const displayLogin = activeAccount?.login || "none";
      const label = config
        ? Object.entries(config.accounts).find(
            ([, login]) => login === displayLogin
          )?.[0]
        : undefined;

      const displayName = label || displayLogin;

      // Show status
      if (
        inferredLogin &&
        activeAccount &&
        inferredLogin !== activeAccount.login
      ) {
        // Mismatch — active ≠ inferred
        this.statusBarItem.text = `$(warning) ${displayName}`;
        this.statusBarItem.tooltip = new vscode.MarkdownString(
          `**ghx:** Active account \`${activeAccount.login}\` ` +
            `doesn't match inferred \`${inferredLogin}\`\n\n` +
            `Reason: ${inferReason || "directory rules"}\n\n` +
            `Click to switch`
        );
        this.statusBarItem.backgroundColor = new vscode.ThemeColor(
          "statusBarItem.warningBackground"
        );
      } else {
        this.statusBarItem.text = `$(person) ${displayName}`;
        this.statusBarItem.tooltip = new vscode.MarkdownString(
          `**ghx:** \`${displayLogin}\` on github.com\n\n` +
            `${inferReason ? `Matched: ${inferReason}\n\n` : ""}` +
            `Click to switch account`
        );
        this.statusBarItem.backgroundColor = undefined;
      }
    } catch {
      this.statusBarItem.text = "$(person) gh?";
      this.statusBarItem.tooltip = "ghx: Could not determine account";
    }
  }
}
