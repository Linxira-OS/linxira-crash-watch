from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from linxira_crash_watch import workspace as workspace_mod
from linxira_crash_watch.events import CrashEvent, iso, utcnow
from linxira_crash_watch.workspace import DEDUPE_WINDOW, Workspace


def make_event(event_id: str, exe: str = "/usr/bin/foo", when=None) -> CrashEvent:
    return CrashEvent(
        id=event_id,
        time=iso(when or utcnow()),
        exe=exe,
        pkg="foo",
        pkg_repo="extra",
        severity="S2",
    )


def test_ensure_creates_repo_files(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / "backlog.json").is_file()
    assert (tmp_path / "mute.json").is_file()
    assert (tmp_path / "INDEX.md").is_file()
    assert ws.is_initialized()


def test_backlog_pin_and_remove(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    event = make_event("e-2026-10-10-0001")
    ws.pin_to_backlog(event)
    assert [item["id"] for item in ws.backlog_items()] == ["e-2026-10-10-0001"]
    assert ws.backlog_has_exe("/usr/bin/foo")
    ws.remove_from_backlog("e-2026-10-10-0001")
    assert ws.backlog_items() == []


def test_backlog_window(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    old = make_event("e-0001", when=utcnow() - timedelta(days=2))
    ws.pin_to_backlog(old)
    assert ws.backlog_has_exe("/usr/bin/foo")
    assert not ws.backlog_has_exe("/usr/bin/foo", within=DEDUPE_WINDOW)


def test_mute_roundtrip(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    assert ws.mute_list() == []
    ws.add_mute("foo")
    assert ws.is_muted("/usr/bin/foo")
    assert ws.mute_list() == ["foo"]
    ws.remove_mute("foo")
    assert ws.mute_list() == []


def test_repeat_count_includes_current(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    ws.store.save(make_event("e-0001"))
    ws.store.save(make_event("e-0002"))
    assert ws.repeat_count("/usr/bin/foo") == 3  # 2 stored + current
    assert ws.repeat_count("/usr/bin/other") == 1


def test_write_index_lists_pending(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    ws.store.save(make_event("e-0001"))
    index = ws.write_index().read_text(encoding="utf-8")
    assert "e-0001" in index
    assert "Pending" in index


def test_ensure_materializes_builtin_skill(tmp_path: Path):
    ws = Workspace(tmp_path).ensure()
    skill = tmp_path / ".agents" / "skills" / "diagnose-crash" / "SKILL.md"
    assert skill.is_file()
    assert "name: diagnose-crash" in skill.read_text(encoding="utf-8")
    assert ".agents/skills/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    # Materialization happens on first creation only; content is not overwritten.
    skill.write_text("# local edit\n", encoding="utf-8")
    ws.ensure()
    assert skill.read_text(encoding="utf-8") == "# local edit\n"

def test_workspace_contains_only_crash_skills(tmp_path: Path, monkeypatch):
    """System skills stay system-wide; the crash workspace copies none of them."""
    assert not hasattr(workspace_mod, "SYSTEM_SKILLS_DIR")
    assert not hasattr(workspace_mod, "CONFIG_SKILL_NAME")

    # Simulate an installed system skill dir; nothing should be picked from it.
    fake_system = tmp_path / "system-skills"
    (fake_system / "linxira-config").mkdir(parents=True)
    (fake_system / "linxira-config" / "SKILL.md").write_text(
        "name: linxira-config\n", encoding="utf-8"
    )
    monkeypatch.setattr(workspace_mod, "SYSTEM_SKILLS_DIR", fake_system, raising=False)
    monkeypatch.setattr(workspace_mod, "CONFIG_SKILL_NAME", "linxira-config", raising=False)

    ws_root = tmp_path / "ws"
    Workspace(ws_root).ensure()

    skills = ws_root / ".agents" / "skills"
    assert (skills / "diagnose-crash" / "SKILL.md").is_file()
    assert not (skills / "linxira-config").exists()
    assert sorted(p.name for p in skills.iterdir()) == ["diagnose-crash"]
