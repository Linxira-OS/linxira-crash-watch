from __future__ import annotations

from pathlib import Path

import pytest

from linxira_crash_watch import config as config_mod
from linxira_crash_watch.config import Config, load_config, parse_duration


def test_parse_duration():
    assert parse_duration("6h") == 6 * 3600
    assert parse_duration("30m") == 1800
    assert parse_duration("7d") == 7 * 86400
    assert parse_duration("45s") == 45


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("soon")


def test_defaults_without_file(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.timeout_seconds == 6 * 3600
    assert cfg.repeat_threshold == 3
    assert cfg.driver_related_escalation is True
    assert cfg.unattended.enabled is False
    assert str(cfg.workspace_path).endswith("Linxira/debug") or "Linxira" in str(cfg.workspace_path)


def test_custom_file(tmp_path: Path):
    path = tmp_path / "crash-watch.toml"
    path.write_text(
        """
[workspace]
path = "/data/debug"

[triage]
timeout = "12h"
repeat_threshold = 5

[escalate]
driver_related = false

[lane.unattended]
enabled = true
schedule = "03:00"
tools = "read"
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.workspace_path == Path("/data/debug")
    assert cfg.timeout_seconds == 12 * 3600
    assert cfg.repeat_threshold == 5
    assert cfg.driver_related_escalation is False
    assert cfg.unattended.enabled is True
    assert cfg.unattended.schedule == "03:00"
    assert cfg.unattended.tools == "read"


def test_bad_timeout_falls_back(tmp_path: Path):
    path = tmp_path / "crash-watch.toml"
    path.write_text("[triage]\ntimeout = 'nonsense'\n", encoding="utf-8")
    assert load_config(path).timeout_seconds == 6 * 3600


def test_state_dir_follows_xdg(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert config_mod.state_dir() == tmp_path / "state" / "linxira-crash-watch"


def test_config_is_frozen():
    cfg = Config(workspace_path=Path("/tmp/ws"))
    with pytest.raises(Exception):
        cfg.timeout_seconds = 1  # type: ignore[misc]