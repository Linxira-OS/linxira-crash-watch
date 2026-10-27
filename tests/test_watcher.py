from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from linxira_crash_watch import notify as notify_mod
from linxira_crash_watch.config import Config, LaneConfig
from linxira_crash_watch.events import (
    STATE_IGNORED,
    STATE_PENDING,
    STATE_PINNED,
    CrashEvent,
    iso,
    utcnow,
)
from linxira_crash_watch.watcher import (
    Watcher,
    normalize_repo,
    parse_coredumpctl_json,
    parse_pacman_qi,
    signal_name,
)
from linxira_crash_watch.workspace import Workspace

LIST_JSON = (
    '[{"pid": 4321, "exe": "/usr/bin/foo", "signal": 11, '
    '"timestamp": "2026-10-10T12:31:02Z", "coredump": "abc"}]'
)


@pytest.fixture(autouse=True)
def _disable_notifications(monkeypatch):
    """Never pop a real desktop notification during tests."""
    monkeypatch.setattr(notify_mod, "available", lambda: False)


class Completed:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def fake_runner(responses: dict[str, tuple[str, int]]):
    def runner(argv, **_kwargs):
        key = " ".join(argv)
        for prefix, (out, code) in responses.items():
            if key.startswith(prefix):
                return Completed(out, code)
        return Completed("", 1)

    return runner


def build_watcher(tmp_path: Path, monkeypatch, responses: dict) -> Watcher:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = Config(workspace_path=tmp_path, unattended=LaneConfig())
    workspace = Workspace(tmp_path).ensure()
    return Watcher(config, workspace, runner=fake_runner(responses))


def test_parse_coredumpctl_json():
    records = parse_coredumpctl_json(LIST_JSON)
    assert len(records) == 1
    record = records[0]
    assert record.pid == 4321
    assert record.signal == "SIGSEGV"
    assert record.exe == "/usr/bin/foo"
    assert record.dump_ref == "abc"


def test_parse_coredumpctl_json_tolerates_garbage():
    assert parse_coredumpctl_json("") == []
    assert parse_coredumpctl_json("not json") == []


def test_signal_name():
    assert signal_name(6) == "SIGABRT"
    assert signal_name("SIGSEGV") == "SIGSEGV"
    assert signal_name("11") == "SIGSEGV"


def test_parse_pacman_qi():
    repo, groups = parse_pacman_qi("Repository : extra\nGroups : plasma\n")
    assert repo == "extra"
    assert groups == ("plasma",)
    repo2, groups2 = parse_pacman_qi("Repository : core\nGroups : None\n")
    assert repo2 == "core"
    assert groups2 == ()


def test_normalize_repo():
    assert normalize_repo("Linxira") == "linxira"
    assert normalize_repo("EXTRA") == "extra"
    assert normalize_repo(None) is None


def test_build_event_classifies_core(tmp_path, monkeypatch):
    responses = {
        "coredumpctl list": (LIST_JSON, 0),
        "pacman -Qoq": ("systemd\n", 0),
        "pacman -Qi": ("Repository : core\nGroups : None\n", 0),
        "coredumpctl info": ("stack: systemd_crash\n", 0),
    }
    watcher = build_watcher(tmp_path, monkeypatch, responses)
    records = watcher.collect()
    event = watcher.build_event(records[0])
    assert event.severity == "S0"
    assert event.pkg == "systemd"
    assert event.pkg_repo == "core"


def test_build_event_driver_related(tmp_path, monkeypatch):
    responses = {
        "coredumpctl list": ('[{"pid": 7, "exe": "/usr/bin/game", "signal": 11, "timestamp": "t"}]', 0),
        "pacman -Qoq": ("game\n", 0),
        "pacman -Qi": ("Repository : extra\nGroups : None\n", 0),
        "coredumpctl info": ("... libEGL.so.1 ...\n", 0),
    }
    watcher = build_watcher(tmp_path, monkeypatch, responses)
    event = watcher.build_event(watcher.collect()[0])
    assert event.driver_related is True
    assert event.driver_hint == "libEGL"
    assert event.severity == "S0"


def test_poll_once_dedupes(tmp_path, monkeypatch):
    responses = {
        "coredumpctl list": (LIST_JSON, 0),
        "pacman -Qoq": ("foo\n", 0),
        "pacman -Qi": ("Repository : extra\nGroups : None\n", 0),
        "coredumpctl info": ("", 0),
    }
    watcher = build_watcher(tmp_path, monkeypatch, responses)
    first = watcher.poll_once()
    assert len(first) == 1
    assert first[0].triage_state == STATE_PENDING
    assert watcher.poll_once() == []


def test_poll_once_respects_mute(tmp_path, monkeypatch):
    responses = {
        "coredumpctl list": (LIST_JSON, 0),
        "pacman -Qoq": ("foo\n", 0),
        "pacman -Qi": ("Repository : extra\nGroups : None\n", 0),
        "coredumpctl info": ("", 0),
    }
    watcher = build_watcher(tmp_path, monkeypatch, responses)
    watcher.workspace.add_mute("foo")
    event = watcher.poll_once()[0]
    assert event.triage_state == STATE_IGNORED
    assert event.triage_reason == "mute"


def test_sweep_timeouts_pins_and_ignores(tmp_path, monkeypatch):
    watcher = build_watcher(tmp_path, monkeypatch, {})
    old = iso(utcnow() - timedelta(hours=7))
    core = CrashEvent(id="e-0001", time=old, exe="/usr/bin/kwin_wayland", pkg="kwin", severity="S0")
    plain = CrashEvent(id="e-0002", time=old, exe="/usr/bin/foo", pkg="foo", pkg_repo="extra", severity="S2")
    fresh = CrashEvent(id="e-0003", time=iso(utcnow()), exe="/usr/bin/bar", pkg="bar", severity="S2")
    for event in (core, plain, fresh):
        watcher.workspace.store.save(event)

    acted = watcher.sweep_timeouts()
    states = {event.id: (event.triage_state, event.triage_reason) for event in acted}
    assert states["e-0001"] == (STATE_PINNED, "auto-core")
    assert states["e-0002"] == (STATE_IGNORED, "auto-user")
    assert "e-0003" not in states
    assert [item["id"] for item in watcher.workspace.backlog_items()] == ["e-0001"]


def test_check_arg_rejects_option_like():
    from linxira_crash_watch.watcher import _check_arg

    with pytest.raises(ValueError):
        _check_arg("--evil")
    assert _check_arg("/usr/bin/foo") == "/usr/bin/foo"

def _saved_event(tmp_path, monkeypatch):
    responses = {
        "coredumpctl list": (LIST_JSON, 0),
        "pacman -Qoq": ("foo\n", 0),
        "pacman -Qi": ("Repository : extra\nGroups : None\n", 0),
        "coredumpctl info": ("", 0),
    }
    watcher = build_watcher(tmp_path, monkeypatch, responses)
    event = watcher.build_event(watcher.collect()[0])
    watcher.workspace.store.save(event)
    return watcher, event


def test_notification_pin_updates_backlog(tmp_path, monkeypatch):
    watcher, event = _saved_event(tmp_path, monkeypatch)
    watcher._apply_notification_action(event, notify_mod.ACTION_PIN)
    saved, _ = watcher.workspace.store.find(event.id)
    assert saved.triage_state == STATE_PINNED
    assert [item["id"] for item in watcher.workspace.backlog_items()] == [event.id]


def test_notification_mute_updates_state(tmp_path, monkeypatch):
    watcher, event = _saved_event(tmp_path, monkeypatch)
    watcher._apply_notification_action(event, notify_mod.ACTION_MUTE)
    saved, _ = watcher.workspace.store.find(event.id)
    assert saved.triage_state == STATE_IGNORED
    assert watcher.workspace.is_muted(event.exe)


def test_notification_copy_writes_command(tmp_path, monkeypatch):
    watcher, event = _saved_event(tmp_path, monkeypatch)
    copied = []
    monkeypatch.setattr(notify_mod, "copy_to_clipboard", lambda text: copied.append(text) or True)
    watcher._apply_notification_action(event, notify_mod.ACTION_COPY)
    assert copied and "zetacode" in copied[0]
    assert "linxira-config capabilities" in copied[0]


def test_notification_investigate_launches_cli(tmp_path, monkeypatch):
    watcher, event = _saved_event(tmp_path, monkeypatch)
    launched = []
    monkeypatch.setattr(watcher, "_launch_investigate", lambda ev: launched.append(ev.id))
    watcher._apply_notification_action(event, notify_mod.ACTION_INVESTIGATE)
    assert launched == [event.id]
