from __future__ import annotations

from pathlib import Path

from linxira_crash_watch.events import (
    SCHEMA,
    STATE_IGNORED,
    STATE_PENDING,
    STATE_PINNED,
    CrashEvent,
    EventStore,
    iso,
    parse_time,
    slugify,
    utcnow,
)


def sample_event(event_id: str = "e-2026-10-10-0001") -> CrashEvent:
    return CrashEvent(
        id=event_id,
        time=iso(utcnow()),
        exe="/usr/bin/foo",
        pid=4321,
        signal="SIGSEGV",
        scope="system",
        pkg="foo",
        pkg_repo="extra",
        pkg_group=("bar",),
        severity="S2",
        dump_ref="coredumpctl:4321",
    )


def test_roundtrip():
    event = sample_event()
    data = event.to_dict()
    assert data["schema"] == SCHEMA
    assert data["pkgRepo"] == "extra"
    assert data["triage"] == {"state": STATE_PENDING, "reason": None, "at": None}
    restored = CrashEvent.from_dict(data)
    assert restored == event


def test_slugify():
    assert slugify("kwin_wayland") == "kwin_wayland"
    assert slugify("a/b c") == "a-b-c"
    assert slugify("") == "crash"


def test_parse_time_handles_z():
    dt = parse_time("2026-10-10T12:31:02Z")
    assert dt.year == 2026 and dt.tzinfo is not None


def test_store_save_find_update(tmp_path: Path):
    store = EventStore(tmp_path)
    event = store.save(sample_event())
    found = store.find("e-2026-10-10-0001")
    assert found is not None
    loaded, path = found
    assert path == event
    assert loaded.pkg == "foo"

    updated = store.update_triage("e-2026-10-10-0001", STATE_PINNED, "user-pin", iso(utcnow()))
    assert updated.triage_state == STATE_PINNED
    assert store.find("e-2026-10-10-0001")[0].triage_reason == "user-pin"


def test_store_counts(tmp_path: Path):
    store = EventStore(tmp_path)
    store.save(sample_event("e-2026-10-10-0001"))
    store.save(sample_event("e-2026-10-10-0002"))
    store.update_triage("e-2026-10-10-0002", STATE_IGNORED, "auto-user", iso(utcnow()))
    counts = store.counts()
    assert counts[STATE_PENDING] == 1
    assert counts[STATE_IGNORED] == 1


def test_batch_dir_layout(tmp_path: Path):
    store = EventStore(tmp_path)
    event = sample_event()
    event.time = "2026-10-10T12:31:02Z"
    path = store.path_for(event)
    assert path.parent.name == "events"
    assert path.parent.parent.name == "2026-10-10-foo"