from __future__ import annotations

import pytest

from linxira_crash_watch import lanes
from linxira_crash_watch.about import ZETACODE


def test_zetacode_is_registered_name():
    assert ZETACODE == "zetacode"


def test_interactive_argv_uses_session_dir():
    argv = lanes.build_agent_argv(lanes.LANE_INTERACTIVE, "/ws", "排查", evidence="/ws/events/e-1.json")
    assert argv[0] == "zetacode"
    assert "--cwd" in argv and "/ws" in argv
    assert "--session-dir" in argv
    assert argv[-1].endswith("@/ws/events/e-1.json")


def test_batch_argv_uses_goal():
    argv = lanes.build_agent_argv(lanes.LANE_BATCH, "/ws", "处理 backlog")
    assert argv[:1] == ["zetacode"]
    assert "--goal" in argv


def test_unattended_argv_is_readonly():
    argv = lanes.build_agent_argv(lanes.LANE_UNATTENDED, "/ws", "分析")
    assert "-p" in argv
    assert f"--tools={lanes.READONLY_TOOLS}" in argv
    assert lanes.READONLY_TOOLS == "read,grep,glob,lsp"


def test_unknown_lane_rejected():
    with pytest.raises(ValueError):
        lanes.build_agent_argv("nope", "/ws", "x")


def test_unattended_gate_is_closed_by_default():
    with pytest.raises(PermissionError):
        lanes.plan_lane(lanes.LANE_UNATTENDED, "/ws", "分析", unattended_enabled=False)


def test_unattended_gate_opens_when_enabled():
    command = lanes.plan_lane(lanes.LANE_UNATTENDED, "/ws", "分析", unattended_enabled=True)
    assert command.lane == lanes.LANE_UNATTENDED
    assert "-p" in command.argv


def test_batch_lane_never_wraps_in_terminal():
    command = lanes.plan_lane(lanes.LANE_BATCH, "/ws", "处理")
    assert command.terminal is None
    assert command.argv[0] == "zetacode"