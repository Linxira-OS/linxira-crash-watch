"""The three agent lanes (design draft section 9).

All three spawn ``zetacode`` — never ``zeta`` or ``omp`` — inside the debug
workspace. Lane ③ (unattended) is off by default and, when enabled, still uses
a read-only tool set so it can only produce ``notes.md``.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .about import ZETACODE

LANE_INTERACTIVE = "interactive"
LANE_BATCH = "batch"
LANE_UNATTENDED = "unattended"
LANES = (LANE_INTERACTIVE, LANE_BATCH, LANE_UNATTENDED)

# Read-only tool set for the unattended lane: no bash/write/edit.
READONLY_TOOLS = "read,grep,glob,lsp"

# Terminal fallback chain, matching the existing Linxira convention.
# 2026-10-27: only terminals that accept an exec flag belong here.  The package
# is ``cosmic-terminal`` but the binary is ``cosmic-term``, and cosmic-term has
# no ``-e``: positional arguments are read as a file or working directory, so
# the process exits at once and the window flashes.  It is handled separately in
# ``_cosmic_term_command`` through a Terminal=true desktop entry.
TERMINAL_CHAIN = (
    ("konsole", ("--hold", "-e")),
    ("alacritty", ("--hold", "-e")),
    ("xterm", ("-hold", "-e")),
)


@dataclass(frozen=True)
class LaneCommand:
    lane: str
    argv: list[str]
    terminal: str | None = None

    @property
    def display(self) -> str:
        return " ".join(self.argv)


def build_agent_argv(
    lane: str,
    workspace: str,
    prompt: str,
    evidence: str | None = None,
) -> list[str]:
    """Build the ``zetacode`` argv for a lane. Never runs the command."""
    text = prompt
    if evidence:
        text = f"{prompt} @{evidence}"
    if lane == LANE_INTERACTIVE:
        return [
            ZETACODE,
            "--cwd",
            workspace,
            "--session-dir",
            f"{workspace}/.zeta/sessions",
            text,
        ]
    if lane == LANE_BATCH:
        return [ZETACODE, "--cwd", workspace, "--goal", text]
    if lane == LANE_UNATTENDED:
        return [
            ZETACODE,
            "--cwd",
            workspace,
            "-p",
            f"--tools={READONLY_TOOLS}",
            text,
        ]
    raise ValueError(f"unknown lane: {lane}")


def find_terminal() -> tuple[str, tuple[str, ...]] | None:
    for name, args in TERMINAL_CHAIN:
        if shutil.which(name):
            return name, args
    return None


def _desktop_exec(argv: list[str]) -> str:
    """Quote an argv list for a desktop entry's ``Exec=`` key."""
    return " ".join(
        '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        for arg in argv
    )


def _cosmic_term_command(argv: list[str]) -> LaneCommand | None:
    """Wrap ``argv`` for cosmic-term, which has no ``-e`` flag.

    A ``Terminal=true`` desktop entry is the only reliable way to hand a
    command to cosmic-term; the entry is removed again after five seconds.
    """
    if not os.access("/usr/bin/cosmic-term", os.X_OK):
        return None
    gtk_launch = shutil.which("gtk-launch")
    if not gtk_launch:
        return None
    share = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    entry_dir = share / "applications"
    entry = entry_dir / f"linxira-crash-watch-{os.getpid()}.desktop"
    try:
        entry_dir.mkdir(parents=True, exist_ok=True)
        entry.write_text(
            "[Desktop Entry]\nType=Application\nName=Linxira Crash Watch\n"
            f"Exec={_desktop_exec(argv)}\n"
            "Terminal=true\nNoDisplay=true\n",
            encoding="utf-8",
        )
    except OSError:
        return None
    subprocess.Popen(
        ["sh", "-c", f"sleep 5; rm -f {shlex.quote(str(entry))}"],
        start_new_session=True,
    )
    return LaneCommand(lane="", argv=[gtk_launch, entry.stem], terminal="cosmic-term")


def wrap_in_terminal(argv: list[str]) -> LaneCommand | None:
    """Wrap an argv in the first available terminal emulator, or None."""
    found = find_terminal()
    if found:
        name, args = found
        return LaneCommand(lane="", argv=[name, *args, *argv], terminal=name)
    return _cosmic_term_command(argv)


def plan_lane(
    lane: str,
    workspace: str,
    prompt: str,
    evidence: str | None = None,
    unattended_enabled: bool = False,
) -> LaneCommand:
    """Produce the command to run for a lane, applying safety gates."""
    if lane == LANE_UNATTENDED and not unattended_enabled:
        raise PermissionError("unattended lane is disabled by configuration")
    argv = build_agent_argv(lane, workspace, prompt, evidence=evidence)
    if lane == LANE_INTERACTIVE:
        wrapped = wrap_in_terminal(argv)
        if wrapped is not None:
            return LaneCommand(lane=lane, argv=wrapped.argv, terminal=wrapped.terminal)
    return LaneCommand(lane=lane, argv=argv)