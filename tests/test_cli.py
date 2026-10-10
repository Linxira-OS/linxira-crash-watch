from __future__ import annotations

from pathlib import Path

from linxira_crash_watch.cli import main
from linxira_crash_watch.events import CrashEvent, STATE_IGNORED, STATE_PENDING
from linxira_crash_watch.workspace import Workspace


def make_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "crash-watch.toml"
    workspace = (tmp_path / "debug").as_posix()
    cfg.write_text(f'[workspace]\npath = "{workspace}"\n', encoding="utf-8")
    return cfg


def seed_event(tmp_path: Path) -> str:
    workspace = Workspace(tmp_path / "debug").ensure()
    event = CrashEvent(
        id="e-2026-10-10-0001",
        time="2026-10-10T12:31:02Z",
        exe="/usr/bin/foo",
        pkg="foo",
        pkg_repo="extra",
        severity="S2",
    )
    workspace.store.save(event)
    return event.id


def test_status(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    assert main(["--config", str(cfg), "status"]) == 0
    out = capsys.readouterr().out
    assert "workspace:" in out
    assert "pending=0" in out


def test_pin_then_list(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    event_id = seed_event(tmp_path)
    capsys.readouterr()
    assert main(["--config", str(cfg), "pin", event_id]) == 0
    assert main(["--config", str(cfg), "list", "--state", "pinned"]) == 0
    out = capsys.readouterr().out
    assert event_id in out

    workspace = Workspace(tmp_path / "debug")
    assert [item["id"] for item in workspace.backlog_items()] == [event_id]


def test_ignore_then_restore(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    event_id = seed_event(tmp_path)
    assert main(["--config", str(cfg), "ignore", event_id]) == 0
    workspace = Workspace(tmp_path / "debug")
    assert workspace.store.find(event_id)[0].triage_state == STATE_IGNORED

    assert main(["--config", str(cfg), "restore", event_id]) == 0
    assert workspace.store.find(event_id)[0].triage_state == STATE_PENDING


def test_mute_cli(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    assert main(["--config", str(cfg), "mute", "foo"]) == 0
    assert main(["--config", str(cfg), "mute", "--list"]) == 0
    out = capsys.readouterr().out
    assert "foo" in out
    assert main(["--config", str(cfg), "mute", "--off", "foo"]) == 0


def test_missing_event_exits_nonzero(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    assert main(["--config", str(cfg), "pin", "nope"]) == 1


def test_investigate_dry_run(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    event_id = seed_event(tmp_path)
    assert main(["--config", str(cfg), "investigate", event_id, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "zetacode" in out


def test_no_command_prints_help(tmp_path: Path, capsys):
    cfg = make_config(tmp_path)
    assert main(["--config", str(cfg)]) == 0
    assert "usage" in capsys.readouterr().out.lower()