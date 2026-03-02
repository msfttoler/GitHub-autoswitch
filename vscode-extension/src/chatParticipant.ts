/**
 * chatParticipant.ts — @ghx Copilot Chat Participant
 *
 * Provides intelligent, LLM-powered account management in Copilot Chat:
 *   /status  — Show accounts and inference signals
 *   /why     — Explain why an account was selected (uses LLM)
 *   /switch  — Switch to a different account
 *   /setup   — Help configure ghx (uses LLM to analyze workspace)
 */

import * as vscode from "vscode";
import { GhxBridge } from "./ghxBridge";

export function registerChatParticipant(
  context: vscode.ExtensionContext,
  bridge: GhxBridge
): void {
  const participant = vscode.chat.createChatParticipant(
    "ghx.chat",
    async (
      request: vscode.ChatRequest,
      chatContext: vscode.ChatContext,
      stream: vscode.ChatResponseStream,
      token: vscode.CancellationToken
    ): Promise<vscode.ChatResult> => {
      switch (request.command) {
        case "status":
          return handleStatus(bridge, stream, token);
        case "why":
          return handleWhy(bridge, request, stream, token);
        case "switch":
          return handleSwitch(bridge, request, stream, token);
        case "setup":
          return handleSetup(bridge, request, stream, token);
        default:
          return handleDefault(bridge, request, stream, token);
      }
    }
  );

  participant.iconPath = new vscode.ThemeIcon("person-add");
  context.subscriptions.push(participant);
}

// ── /status ────────────────────────────────────────────────────────────

async function handleStatus(
  bridge: GhxBridge,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<vscode.ChatResult> {
  stream.progress("Checking GitHub accounts...");

  const accounts = await bridge.getAccounts();

  if (accounts.length === 0) {
    stream.markdown(
      "No GitHub accounts found. Run `gh auth login` in your terminal to add one."
    );
    return {};
  }

  // Group by host
  const hosts = new Map<string, typeof accounts>();
  for (const acct of accounts) {
    const list = hosts.get(acct.host) || [];
    list.push(acct);
    hosts.set(acct.host, list);
  }

  const config = bridge.loadConfig();

  stream.markdown("## GitHub Account Status\n\n");

  for (const [host, hostAccounts] of hosts) {
    stream.markdown(`### ${host}\n\n`);
    stream.markdown("| Account | Label | Status |\n|---|---|---|\n");

    for (const acct of hostAccounts) {
      const label = config
        ? Object.entries(config.accounts).find(
            ([, login]) => login === acct.login
          )?.[0] || ""
        : "";
      const status = acct.active ? "**● active**" : "—";
      stream.markdown(`| \`${acct.login}\` | ${label} | ${status} |\n`);
    }
    stream.markdown("\n");
  }

  // Show inference for current workspace
  const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (workspacePath) {
    stream.markdown(`### Workspace Inference\n\n`);
    stream.markdown(`**Directory:** \`${workspacePath}\`\n\n`);

    const result = await bridge.inferAccount(workspacePath);
    if (result.login) {
      stream.markdown(
        `**Inferred account:** \`${result.login}\`\n\n`
      );
      stream.markdown("| Signal | Confidence | Detail |\n|---|---|---|\n");
      for (const sig of result.allSignals) {
        const isWinner = result.signals.includes(sig);
        const bar = confidenceBar(sig.confidence);
        const marker = isWinner ? "→" : " ";
        stream.markdown(
          `| ${marker} ${sig.source} | ${bar} | ${sig.detail} |\n`
        );
      }
    } else {
      stream.markdown(
        "**Inferred account:** _(none — no rules matched)_\n"
      );
    }
  }

  // Offer quick actions
  stream.markdown("\n---\n");
  stream.button({
    command: "ghx.switchAccount",
    title: "Switch Account",
  });
  stream.button({
    command: "ghx.openConfig",
    title: "Open Config",
  });

  return {};
}

// ── /why ───────────────────────────────────────────────────────────────

async function handleWhy(
  bridge: GhxBridge,
  request: vscode.ChatRequest,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<vscode.ChatResult> {
  const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!workspacePath) {
    stream.markdown("No workspace folder is open.");
    return {};
  }

  stream.progress("Analyzing workspace context...");

  // Gather all context
  const context = await bridge.gatherWorkspaceContext(workspacePath);
  const inferResult = await bridge.inferAccount(workspacePath);

  // Use the Copilot LLM to generate a natural-language explanation
  const [model] = await vscode.lm.selectChatModels({
    vendor: "copilot",
    family: "gpt-4o",
  });

  if (!model) {
    // Fallback: structured output without LLM
    return handleWhyFallback(inferResult, stream);
  }

  const messages = [
    vscode.LanguageModelChatMessage.User(
      `You are ghx, an intelligent GitHub CLI account switcher. ` +
        `The user wants to understand why a particular GitHub account was selected ` +
        `(or not selected) for their current workspace.\n\n` +
        `Here is the workspace context:\n${context}\n\n` +
        `Here is the inference result:\n` +
        `- Inferred login: ${inferResult.login || "(none)"}\n` +
        `- All signals:\n${inferResult.allSignals.map((s) => `  - [${s.source}] ${s.detail} (confidence: ${s.confidence})`).join("\n")}\n\n` +
        `${request.prompt ? `The user also asked: "${request.prompt}"\n\n` : ""}` +
        `Explain clearly and concisely why this account was chosen. ` +
        `If no account was inferred, suggest what the user should do. ` +
        `Use markdown formatting. Be helpful and specific.`
    ),
  ];

  const response = await model.sendRequest(messages, {}, token);

  for await (const chunk of response.text) {
    stream.markdown(chunk);
  }

  return {};
}

function handleWhyFallback(
  result: {
    login: string | undefined;
    signals: { source: string; detail: string; confidence: number }[];
    allSignals: { source: string; detail: string; confidence: number }[];
  },
  stream: vscode.ChatResponseStream
): vscode.ChatResult {
  stream.markdown("## Account Inference Explanation\n\n");

  if (result.login) {
    stream.markdown(`**Inferred account:** \`${result.login}\`\n\n`);
  } else {
    stream.markdown("**No account inferred.** No rules matched this workspace.\n\n");
    stream.markdown("Try running `@ghx /setup` to configure account rules.\n\n");
    return {};
  }

  if (result.allSignals.length > 0) {
    stream.markdown("**Signals evaluated:**\n\n");
    for (const sig of result.allSignals) {
      const isWinner = result.signals.some(
        (s) => s.source === sig.source && s.confidence === sig.confidence
      );
      const marker = isWinner ? "→" : " ";
      stream.markdown(
        `${marker} **${sig.source}** (${(sig.confidence * 100).toFixed(0)}%) — ${sig.detail}\n\n`
      );
    }
  }

  return {};
}

// ── /switch ────────────────────────────────────────────────────────────

async function handleSwitch(
  bridge: GhxBridge,
  request: vscode.ChatRequest,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<vscode.ChatResult> {
  const accounts = await bridge.getAccounts();
  const config = bridge.loadConfig();

  if (accounts.length === 0) {
    stream.markdown(
      "No GitHub accounts found. Run `gh auth login` first."
    );
    return {};
  }

  // If the user specified an account in the prompt
  const requestedAccount = request.prompt.trim();
  if (requestedAccount) {
    // Try to resolve it
    let targetLogin: string | undefined;

    if (config) {
      targetLogin =
        config.accounts[requestedAccount] || undefined;
    }
    if (!targetLogin) {
      targetLogin = accounts.find(
        (a) => a.login === requestedAccount
      )?.login;
    }

    if (targetLogin) {
      stream.progress(`Switching to ${targetLogin}...`);
      const result = await bridge.switchAccount(targetLogin);
      if (result.success) {
        stream.markdown(`✅ **${result.message}**`);
      } else {
        stream.markdown(`❌ ${result.message}`);
      }
      return {};
    }

    stream.markdown(
      `Could not find account "${requestedAccount}". Available accounts:\n\n`
    );
  } else {
    stream.markdown("Which account would you like to switch to?\n\n");
  }

  // Show available accounts as buttons
  for (const acct of accounts) {
    const label = config
      ? Object.entries(config.accounts).find(
          ([, login]) => login === acct.login
        )?.[0]
      : undefined;
    const displayLabel = label ? `${label} (${acct.login})` : acct.login;
    const active = acct.active ? " ● active" : "";
    const host =
      acct.host !== "github.com" ? ` [${acct.host}]` : "";

    stream.markdown(
      `- \`${displayLabel}\`${host}${active}\n`
    );
  }

  stream.markdown(
    `\nTry: \`@ghx /switch work\` or \`@ghx /switch your-login\``
  );

  return {};
}

// ── /setup ─────────────────────────────────────────────────────────────

async function handleSetup(
  bridge: GhxBridge,
  request: vscode.ChatRequest,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<vscode.ChatResult> {
  stream.progress("Analyzing your workspace and accounts...");

  const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const context = workspacePath
    ? await bridge.gatherWorkspaceContext(workspacePath)
    : "No workspace folder open.";

  const config = bridge.loadConfig();
  const configExists = config !== null;

  // Use LLM to generate smart configuration
  const [model] = await vscode.lm.selectChatModels({
    vendor: "copilot",
    family: "gpt-4o",
  });

  if (!model) {
    stream.markdown(
      "Copilot model not available. Run `ghx init` in your terminal for interactive setup."
    );
    return {};
  }

  const messages = [
    vscode.LanguageModelChatMessage.User(
      `You are ghx, an intelligent GitHub CLI account switcher setup assistant.\n\n` +
        `The user wants to configure ghx. Here is their workspace context:\n${context}\n\n` +
        `Config file exists: ${configExists}\n` +
        `Config path: ${bridge.getConfigPath()}\n` +
        `${configExists ? `Current config: ${JSON.stringify(config)}` : ""}\n\n` +
        `${request.prompt ? `The user said: "${request.prompt}"\n\n` : ""}` +
        `Help them set up ghx. Based on the workspace context:\n` +
        `1. Analyze which accounts they have and what the workspace suggests\n` +
        `2. Suggest a config.yml with appropriate rules\n` +
        `3. Explain what each rule does\n` +
        `4. If a config already exists, suggest improvements\n\n` +
        `Output a complete, ready-to-use YAML config in a code block. ` +
        `Use the ghx config format with accounts, hosts, rules, default_account, and behavior sections. ` +
        `Be specific to their actual accounts and workspace.`
    ),
  ];

  const response = await model.sendRequest(messages, {}, token);

  for await (const chunk of response.text) {
    stream.markdown(chunk);
  }

  stream.markdown("\n\n---\n");
  stream.button({
    command: "ghx.openConfig",
    title: "Open/Create Config File",
  });

  return {};
}

// ── Default (no command) ───────────────────────────────────────────────

async function handleDefault(
  bridge: GhxBridge,
  request: vscode.ChatRequest,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<vscode.ChatResult> {
  // If the user typed something, use LLM to handle it
  if (request.prompt.trim()) {
    stream.progress("Thinking...");

    const workspacePath =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const context = workspacePath
      ? await bridge.gatherWorkspaceContext(workspacePath)
      : "No workspace folder open.";

    const [model] = await vscode.lm.selectChatModels({
      vendor: "copilot",
      family: "gpt-4o",
    });

    if (!model) {
      stream.markdown(
        "I'm **ghx**, the GitHub account switcher. Try these commands:\n\n" +
          "- `/status` — See your accounts and which one is active\n" +
          "- `/why` — Understand why an account was selected\n" +
          "- `/switch <account>` — Switch to a different account\n" +
          "- `/setup` — Get help configuring ghx\n"
      );
      return {};
    }

    const messages = [
      vscode.LanguageModelChatMessage.User(
        `You are ghx, an intelligent GitHub CLI account switcher assistant ` +
          `embedded in VS Code as a Copilot Chat participant.\n\n` +
          `Workspace context:\n${context}\n\n` +
          `The user asked: "${request.prompt}"\n\n` +
          `Help them with their GitHub account management question. ` +
          `You can explain how ghx works, help debug account issues, ` +
          `suggest configuration changes, or answer questions about their setup. ` +
          `Be concise and helpful. Use markdown formatting.`
      ),
    ];

    const response = await model.sendRequest(messages, {}, token);

    for await (const chunk of response.text) {
      stream.markdown(chunk);
    }

    return {};
  }

  // No prompt — show help
  stream.markdown(
    "# 👤 ghx — GitHub Account Switcher\n\n" +
      "I help you manage multiple GitHub CLI accounts. Here's what I can do:\n\n" +
      "| Command | Description |\n|---|---|\n" +
      "| `/status` | Show your accounts, active account, and inference signals |\n" +
      "| `/why` | Explain why a specific account was chosen for this workspace |\n" +
      "| `/switch <account>` | Switch to a different GitHub account |\n" +
      "| `/setup` | Help configure ghx with smart rules for your workspace |\n\n" +
      "You can also ask me questions in natural language, like:\n" +
      '- *"Which account am I using?"*\n' +
      '- *"Why is my work account active in this repo?"*\n' +
      '- *"Help me set up auto-switching for my projects"*\n'
  );

  return {};
}

// ── Helpers ────────────────────────────────────────────────────────────

function confidenceBar(confidence: number): string {
  const filled = Math.round(confidence * 5);
  return "█".repeat(filled) + "░".repeat(5 - filled);
}
