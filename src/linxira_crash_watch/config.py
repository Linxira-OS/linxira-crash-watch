"""Configuration loading for linxira-crash-watch.

Config lives at ``~/.config/linxira/crash-watch.toml`` (see the design draft,
section 12). Every field has a safe default so the daemon runs before the user
ever writes a config file.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORKSPACE = "~/Linxira/debug"
DEFAULT_TIMEOUT = "6h"
DEFAULT_REPEAT_THRESHOLD = 3
DEFAULT_UNATTENDED_TOOLS = "read,grep,glob,lsp"
DEFAULT_UNATTENDED_SCHEDULE = "04:00"
CONFIG_RELATIVE = ".config/linxira/crash-watch.toml"

_DURATION_RE = re.compile(r"^\s*(?P<num>\d+)\s*(?P<unit>[smhd])\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int:
    """Parse a compact duration such as ``6h``, ``30m`` or ``7d`` into seconds."""
    match = _DURATION_RE.match(str(text))
    if not match:
        raise ValueError(f"invalid duration: {text!r} (expected e.g. '6h', '30m', '7d')")
    return int(match.group("num")) * _UNITS[match.group("unit")]


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()


def state_home() -> Path:
    """Runtime state (seen-crash ledger) — not part of the debug workspace."""
    return Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()


def state_dir() -> Path:
    return state_home() / "linxira-crash-watch"


def default_config_path() -> Path:
    return config_home() / "linxira" / "crash-watch.toml"


@dataclass(frozen=True)
class LaneConfig:
    enabled: bool = False
    schedule: str = DEFAULT_UNATTENDED_SCHEDULE
    tools: str = DEFAULT_UNATTENDED_TOOLS


@dataclass(frozen=True)
class Config:
    workspace_path: Path
    timeout_seconds: int = 6 * 3600
    repeat_threshold: int = DEFAULT_REPEAT_THRESHOLD
    driver_related_escalation: bool = True
    unattended: LaneConfig = LaneConfig()

    @property
    def timeout(self) -> str:
        return self.timeout_seconds


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def load_config(path: Path | None = None) -> Config:
    """Load config, falling back to defaults for any missing field or file."""
    path = path or default_config_path()
    data: dict = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))

    workspace = data.get("workspace", {}) or {}
    triage = data.get("triage", {}) or {}
    escalate = data.get("escalate", {}) or {}
    lane = (data.get("lane", {}) or {}).get("unattended", {}) or {}

    raw_timeout = triage.get("timeout", DEFAULT_TIMEOUT)
    try:
        timeout_seconds = parse_duration(raw_timeout)
    except ValueError:
        timeout_seconds = parse_duration(DEFAULT_TIMEOUT)

    repeat_threshold = triage.get("repeat_threshold", DEFAULT_REPEAT_THRESHOLD)
    if not isinstance(repeat_threshold, int) or repeat_threshold < 1:
        repeat_threshold = DEFAULT_REPEAT_THRESHOLD

    return Config(
        workspace_path=Path(workspace.get("path", DEFAULT_WORKSPACE)).expanduser(),
        timeout_seconds=timeout_seconds,
        repeat_threshold=repeat_threshold,
        driver_related_escalation=_as_bool(escalate.get("driver_related"), True),
        unattended=LaneConfig(
            enabled=_as_bool(lane.get("enabled"), False),
            schedule=str(lane.get("schedule", DEFAULT_UNATTENDED_SCHEDULE)),
            tools=str(lane.get("tools", DEFAULT_UNATTENDED_TOOLS)),
        ),
    )