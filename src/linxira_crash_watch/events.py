"""Crash-event data model and on-disk event store.

Events are text-only JSON files (schema ``org.linxira.crash-event.v1``) written
under the debug workspace ``batches/<date>-<slug>/events/``. The raw core dump
never enters the workspace; only a ``dumpRef`` (``coredumpctl:<id>``) is stored.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = "org.linxira.crash-event.v1"

STATE_PENDING = "pending"
STATE_PINNED = "pinned"
STATE_IGNORED = "ignored"
STATE_INVESTIGATED = "investigated"
STATES = (STATE_PENDING, STATE_PINNED, STATE_IGNORED, STATE_INVESTIGATED)

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def slugify(text: str, fallback: str = "crash") -> str:
    slug = _SLUG_RE.sub("-", (text or "").strip()).strip("-")
    return slug or fallback


@dataclass
class CrashEvent:
    """One crash, in the schema documented in the design draft section 6."""

    id: str
    time: str
    exe: str
    pid: int = 0
    signal: str = "UNKNOWN"
    scope: str = "user"
    pkg: str | None = None
    pkg_repo: str | None = None
    pkg_group: tuple[str, ...] = field(default_factory=tuple)
    driver_related: bool = False
    driver_hint: str | None = None
    repeat: int = 1
    severity: str = "S2"
    triage_state: str = STATE_PENDING
    triage_reason: str | None = None
    triage_at: str | None = None
    dump_ref: str | None = None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "time": self.time,
            "exe": self.exe,
            "pid": self.pid,
            "signal": self.signal,
            "scope": self.scope,
            "pkg": self.pkg,
            "pkgRepo": self.pkg_repo,
            "pkgGroup": list(self.pkg_group),
            "driverRelated": self.driver_related,
            "driverHint": self.driver_hint,
            "repeat": self.repeat,
            "severity": self.severity,
            "triage": {
                "state": self.triage_state,
                "reason": self.triage_reason,
                "at": self.triage_at,
            },
            "dumpRef": self.dump_ref,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CrashEvent":
        triage = data.get("triage", {}) or {}
        return cls(
            id=data["id"],
            time=data["time"],
            exe=data.get("exe", ""),
            pid=int(data.get("pid", 0)),
            signal=data.get("signal", "UNKNOWN"),
            scope=data.get("scope", "user"),
            pkg=data.get("pkg"),
            pkg_repo=data.get("pkgRepo"),
            pkg_group=tuple(data.get("pkgGroup", []) or ()),
            driver_related=bool(data.get("driverRelated", False)),
            driver_hint=data.get("driverHint"),
            repeat=int(data.get("repeat", 1)),
            severity=data.get("severity", "S2"),
            triage_state=triage.get("state", STATE_PENDING),
            triage_reason=triage.get("reason"),
            triage_at=triage.get("at"),
            dump_ref=data.get("dumpRef"),
        )


class EventStore:
    """Reads and writes crash events inside a debug workspace."""

    def __init__(self, workspace_path: Path):
        self.root = Path(workspace_path)

    @property
    def batches_dir(self) -> Path:
        return self.root / "batches"

    def batch_dir(self, date_str: str, slug: str) -> Path:
        return self.batches_dir / f"{date_str}-{slugify(slug)}"

    def path_for(self, event: CrashEvent) -> Path:
        date_str = parse_time(event.time).strftime("%Y-%m-%d")
        return self.batch_dir(date_str, Path(event.exe).name or "crash") / "events" / f"{event.id}.json"

    def save(self, event: CrashEvent) -> Path:
        path = self.path_for(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(event.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def find(self, event_id: str) -> tuple[CrashEvent, Path] | None:
        for path in sorted(self.batches_dir.glob("*/events/*.json")):
            if path.stem == event_id:
                return CrashEvent.from_dict(json.loads(path.read_text(encoding="utf-8"))), path
        return None

    def iter_events(self) -> Iterator[CrashEvent]:
        paths = sorted(self.batches_dir.glob("*/events/*.json"))
        for path in paths:
            try:
                yield CrashEvent.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError):
                continue

    def update_triage(self, event_id: str, state: str, reason: str | None, at: str) -> CrashEvent:
        found = self.find(event_id)
        if not found:
            raise KeyError(event_id)
        event, path = found
        event.triage_state = state
        event.triage_reason = reason
        event.triage_at = at
        path.write_text(
            json.dumps(event.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return event

    def counts(self) -> dict[str, int]:
        result = {state: 0 for state in STATES}
        for event in self.iter_events():
            result[event.triage_state] = result.get(event.triage_state, 0) + 1
        return result


__all__ = [
    "SCHEMA",
    "STATES",
    "STATE_PENDING",
    "STATE_PINNED",
    "STATE_IGNORED",
    "STATE_INVESTIGATED",
    "CrashEvent",
    "EventStore",
    "utcnow",
    "iso",
    "parse_time",
    "slugify",
]