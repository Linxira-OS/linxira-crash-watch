"""Desktop notification with action buttons.

Sends a notification through ``notify-send`` (libnotify). No shell is used: the
argument vector is fixed and the only variable parts are the title, body, and
program name. If no notification daemon is available the call degrades to a
no-op — capture and triage still work at zero token cost.

Action keys mirror the CLI: ``investigate``, ``pin``, ``mute``.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

NOTIFY_SEND = "notify-send"
APP_NAME = "Linxira Crash Watch"
ICON = "dialog-warning"

ACTION_INVESTIGATE = "investigate"
ACTION_COPY = "copy"
ACTION_PIN = "pin"
ACTION_MUTE = "mute"

DEFAULT_ACTIONS = (
    (ACTION_INVESTIGATE, "立即排查"),
    (ACTION_COPY, "复制提示词"),
    (ACTION_PIN, "Pin"),
    (ACTION_MUTE, "静音"),
)

CLIPBOARD_COMMANDS = (
    ("wl-copy",),
    ("xclip", "-selection", "clipboard"),
    ("xsel", "--clipboard", "--input"),
)


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    action: str | None = None


def available() -> bool:
    return shutil.which(NOTIFY_SEND) is not None


def build_argv(
    title: str,
    body: str,
    actions=DEFAULT_ACTIONS,
    urgency: str = "critical",
) -> list[str]:
    argv = [NOTIFY_SEND, f"--app-name={APP_NAME}", f"--icon={ICON}", f"--urgency={urgency}"]
    if actions:
        argv.append("--wait")
        for key, label in actions:
            argv.append(f"--action={key}={label}")
    argv.extend([title, body])
    return argv


def notify(
    title: str,
    body: str,
    actions=DEFAULT_ACTIONS,
    urgency: str = "critical",
    runner=subprocess.run,
) -> NotificationResult:
    """Show a notification and return the action the user picked (if any)."""
    if not available():
        return NotificationResult(sent=False)
    try:
        completed = runner(
            build_argv(title, body, actions=actions, urgency=urgency),
            capture_output=True,
            text=True,
            timeout=6 * 3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return NotificationResult(sent=False)
    action = (completed.stdout or "").strip() or None
    return NotificationResult(sent=True, action=action)


def copy_to_clipboard(text: str, runner=subprocess.run) -> bool:
    """Copy text to the session clipboard. No shell; first available tool wins."""
    for command in CLIPBOARD_COMMANDS:
        if shutil.which(command[0]) is None:
            continue
        try:
            result = runner(command, input=text, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return True
    return False


def crash_summary(event) -> tuple[str, str]:
    """Build (title, body) for a crash event."""
    name = str(event.exe).rsplit("/", 1)[-1] or event.exe
    title = f"{name} 崩溃 ({event.severity})"
    body = f"信号 {event.signal}"
    if event.pkg:
        body += f" · 包 {event.pkg}"
    if event.driver_hint:
        body += f" · 驱动 {event.driver_hint}"
    body += "\n点击可交给 zeta 排查、复制提示词,或 Pin / 静音。"
    return title, body