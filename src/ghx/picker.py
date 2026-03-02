"""Interactive account picker for terminal UI.

Provides both a full arrow-key-navigable picker (TTY)
and a simple numbered fallback (non-TTY / piped input).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ghx.inference import Signal

# ANSI escape codes
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
WHITE = "\033[37m"


@dataclass
class PickerOption:
    login: str
    label: str | None = None
    host: str = "github.com"
    active: bool = False
    signals: list[Signal] | None = None


def pick_account(
    options: list[PickerOption], prompt: str = "Select account"
) -> PickerOption | None:
    """Display an interactive account picker.

    Returns the selected option, or None if cancelled.
    Falls back to simple_prompt on non-TTY or if curses/termios unavailable.
    """
    if not options:
        return None

    if not sys.stdin.isatty():
        return simple_prompt(options, prompt)

    try:
        return _interactive_pick(options, prompt)
    except Exception:
        return simple_prompt(options, prompt)


def _interactive_pick(
    options: list[PickerOption], prompt: str
) -> PickerOption | None:
    """Arrow-key picker using raw terminal mode."""
    import termios
    import tty

    selected = 0
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        _draw(options, selected, prompt)

        while True:
            ch = sys.stdin.read(1)

            if ch == "\x1b":  # Escape sequence
                seq = sys.stdin.read(2)
                if seq == "[A":  # Up arrow
                    selected = (selected - 1) % len(options)
                elif seq == "[B":  # Down arrow
                    selected = (selected + 1) % len(options)
                elif not seq or seq[0] != "[":  # Plain Escape
                    _move_past(options)
                    return None
            elif ch in ("\r", "\n"):  # Enter
                _move_past(options)
                return options[selected]
            elif ch in ("q", "\x03"):  # q or Ctrl-C
                _move_past(options)
                return None
            elif ch == "k":  # vim up
                selected = (selected - 1) % len(options)
            elif ch == "j":  # vim down
                selected = (selected + 1) % len(options)

            _redraw(options, selected, prompt)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _move_past(options: list[PickerOption]) -> None:
    """Move cursor below the picker display."""
    total_lines = len(options) + 4  # header + blank + options + footer
    sys.stdout.write(f"\033[{total_lines}B\r\n")
    sys.stdout.flush()


def _draw(options: list[PickerOption], selected: int, prompt: str) -> None:
    """Initial draw of the picker."""
    out: list[str] = []
    out.append(f"\r\n{BOLD}{CYAN}  {prompt}{RESET}\r\n\r\n")

    for i, opt in enumerate(options):
        out.append(_format_option(opt, i == selected))

    out.append(f"\r\n{DIM}  ↑↓/jk navigate · Enter select · Esc cancel{RESET}\r\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def _redraw(options: list[PickerOption], selected: int, prompt: str) -> None:
    """Move cursor up and re-draw."""
    lines_up = len(options) + 4
    sys.stdout.write(f"\033[{lines_up}A\r")
    _draw(options, selected, prompt)


def _format_option(opt: PickerOption, is_selected: bool) -> str:
    """Format a single picker option line."""
    pointer = f"{GREEN}  ❯ " if is_selected else "    "
    color = f"{WHITE}{BOLD}" if is_selected else DIM

    parts = [f"{pointer}{color}{opt.login}{RESET}"]

    # Label
    if opt.label and opt.label != opt.login:
        parts.append(f" {DIM}({opt.label}){RESET}")

    # Host (only show if not github.com)
    if opt.host != "github.com":
        parts.append(f" {DIM}[{opt.host}]{RESET}")

    # Active indicator
    if opt.active:
        parts.append(f" {GREEN}● active{RESET}")

    # Signal hint
    if opt.signals:
        hint = opt.signals[0].detail
        parts.append(f" {DIM}← {hint}{RESET}")

    parts.append("\r\n")
    return "".join(parts)


def simple_prompt(
    options: list[PickerOption], prompt: str = "Select account"
) -> PickerOption | None:
    """Fallback numbered prompt for non-TTY environments."""
    print(f"\n  {prompt}:\n")

    for i, opt in enumerate(options):
        active = " ● active" if opt.active else ""
        label = f" ({opt.label})" if opt.label and opt.label != opt.login else ""
        host = f" [{opt.host}]" if opt.host != "github.com" else ""
        print(f"  [{i + 1}] {opt.login}{label}{host}{active}")

    print()
    try:
        choice = input("  Enter number (or q to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() == "q" or not choice:
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx]
    except ValueError:
        pass

    print("  Invalid selection.")
    return None
