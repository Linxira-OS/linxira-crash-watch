"""Shared agent prompts and command rendering for crash-watch."""

from __future__ import annotations

import shlex
from pathlib import Path

from .lanes import LANE_INTERACTIVE, build_agent_argv

PROMPT = (
    "排查这批崩溃:先建立事实(backtrace、复现条件、是否驱动相关),"
    "再判断是否值得上报上游;只出结论,不改系统。"
    "系统配置能力见 .agents/skills/linxira-config/SKILL.md;"
    "需要机器可读清单时运行 linxira-config capabilities --json。"
)


def agent_argv(workspace: str | Path, evidence: str | Path) -> list[str]:
    return build_agent_argv(
        LANE_INTERACTIVE,
        str(workspace),
        PROMPT,
        evidence=str(evidence),
    )


def command_text(workspace: str | Path, evidence: str | Path) -> str:
    """A copy-pasteable zetacode command for notifications/clipboard."""
    return shlex.join(agent_argv(workspace, evidence))
