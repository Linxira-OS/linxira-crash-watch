"""The three agent lanes (design draft section 9).

All three spawn ``zetacode`` — never ``zeta`` or ``omp`` — inside the debug
workspace. Lane ③ (unattended) is off by default and, when enabled, still uses
a read-only tool set so it can only produce ``notes.md``.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass

from .about import ZETACODE

LANE_INTERACTIVE = "interactive"
LANE_BATCH = "batch"
LANE_UNATTENDED = "unattended"
LANES = (LANE_INTERACTIVE, LANE_BATCH, LANE_UNATTENDED)

# Read-only tool set for the unattended lane: no bash/write/edit.
READONLY_TOOLS = "read,grep,glob,lsp"

# Terminal fallback chain, matching the existing Linxira convention.
TERMINAL_CHAIN = (
    ("konsole", ("-e",)),
    ("cosmic-terminal", ("-e",)),
    ("xterm", ("-e",)),
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


def wrap_in_terminal(argv: list[str]) -> LaneCommand | None:
    """Wrap an argv in the first available terminal emulator, or None."""
    found = find_terminal()
    if not found:
        return None
    name, args = found
    return LaneCommand(lane="", argv=[name, *args, *argv], terminal=name)


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