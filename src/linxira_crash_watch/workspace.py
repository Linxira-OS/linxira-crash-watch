"""Debug workspace manager.

The workspace (default ``~/Linxira/debug``) is a git repository holding only
text: crash events, backtraces, notes, and patches. It is the sole contract
between the watcher and the agent — no socket, no HTTP, offline-safe.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .events import CrashEvent, EventStore, iso, parse_time, utcnow

GITIGNORE = """\
# Raw core dumps never enter the workspace — they stay in systemd-coredump's
# store and are referenced by dumpRef. Only text evidence is committed.
*.core
core.*
*.zst
*.dmp
*.tar
*.tar.*

# Built-in agent skills are materialized tooling, not crash evidence.
.agents/skills/
"""

# The built-in diagnose-crash skill ships inside the package; the workspace
# manager materializes it under the standard agent path on first creation.
SKILL_NAME = "diagnose-crash"
SKILL_SOURCE = Path(__file__).parent / "skills" / SKILL_NAME / "SKILL.md"

INDEX_HEADER = """\
# Linxira debug workspace

Text-only crash evidence for agent-assisted diagnosis. Raw core dumps are never
stored here; each event keeps a `dumpRef` into systemd-coredump's own store.

"""

# How long a previous Pin keeps future crashes of the same program de-duplicated.
DEDUPE_WINDOW = timedelta(hours=24)


@dataclass
class Workspace:
    path: Path
    store: EventStore

    def __init__(self, path: Path):
        self.path = Path(path)
        self.store = EventStore(self.path)

    # -- lifecycle ---------------------------------------------------------
    def ensure(self) -> "Workspace":
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "batches").mkdir(exist_ok=True)
        gitignore = self.path / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(GITIGNORE, encoding="utf-8")
        if not (self.path / "backlog.json").exists():
            self._write_backlog({"items": []})
        if not (self.path / "mute.json").exists():
            self._write_json(self.path / "mute.json", {"programs": []})
        self._materialize_skill()
        self._git_init()
        self.write_index()
        return self

    def is_initialized(self) -> bool:
        return (self.path / ".git").exists() and (self.path / "backlog.json").exists()

    def _git_init(self) -> None:
        if (self.path / ".git").exists():
            return
        try:
            subprocess.run(
                ["git", "init", "-q", str(self.path)],
                check=False,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def _materialize_skill(self) -> None:
        """Write the built-in diagnose-crash skill under the standard agent path.

        Zero-install: the skill ships with the package and any agent opening the
        workspace discovers ``.agents/skills/diagnose-crash/SKILL.md`` directly.
        Existing content is never overwritten.
        """
        target = self.path / ".agents" / "skills" / SKILL_NAME / "SKILL.md"
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(SKILL_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")

    # -- backlog -----------------------------------------------------------
    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_backlog(self, payload: dict) -> None:
        self._write_json(self.path / "backlog.json", payload)

    def backlog(self) -> dict:
        path = self.path / "backlog.json"
        if not path.is_file():
            return {"items": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def backlog_items(self) -> list[dict]:
        return list(self.backlog().get("items", []))

    def pin_to_backlog(self, event: CrashEvent) -> None:
        payload = self.backlog()
        items = [item for item in payload.get("items", []) if item.get("id") != event.id]
        items.append(
            {
                "id": event.id,
                "exe": event.exe,
                "pkg": event.pkg,
                "severity": event.severity,
                "reason": event.triage_reason,
                "time": event.time,
                "dumpRef": event.dump_ref,
            }
        )
        payload["items"] = sorted(items, key=lambda item: item.get("time", ""))
        self._write_backlog(payload)

    def remove_from_backlog(self, event_id: str) -> None:
        payload = self.backlog()
        payload["items"] = [item for item in payload.get("items", []) if item.get("id") != event_id]
        self._write_backlog(payload)

    def backlog_has_exe(
        self,
        exe: str,
        within: timedelta | None = None,
        now=None,
    ) -> bool:
        """True when ``exe`` is already in the backlog (optionally recently)."""
        now = now or utcnow()
        for item in self.backlog_items():
            if item.get("exe") != exe:
                continue
            if within is None:
                return True
            try:
                when = parse_time(item.get("time", ""))
            except (ValueError, TypeError):
                return True
            if now - when <= within:
                return True
        return False

    # -- mute list ---------------------------------------------------------
    def mute_list(self) -> list[str]:
        path = self.path / "mute.json"
        if not path.is_file():
            return []
        return list(json.loads(path.read_text(encoding="utf-8")).get("programs", []))

    def is_muted(self, exe: str) -> bool:
        name = Path(exe).name
        muted = self.mute_list()
        return name in muted or exe in muted

    def add_mute(self, program: str) -> list[str]:
        programs = self.mute_list()
        if program not in programs:
            programs.append(program)
            self._write_json(self.path / "mute.json", {"programs": sorted(programs)})
        return self.mute_list()

    def remove_mute(self, program: str) -> list[str]:
        programs = [p for p in self.mute_list() if p != program]
        self._write_json(self.path / "mute.json", {"programs": sorted(programs)})
        return self.mute_list()

    # -- repeat counting ---------------------------------------------------
    def repeat_count(self, exe: str, window: timedelta = timedelta(days=7), now=None) -> int:
        now = now or utcnow()
        count = 0
        for event in self.store.iter_events():
            if event.exe != exe:
                continue
            try:
                when = parse_time(event.time)
            except (ValueError, TypeError):
                continue
            if timedelta(0) <= (now - when) <= window:
                count += 1
        return count + 1  # include the current crash

    # -- index -------------------------------------------------------------
    def write_index(self) -> Path:
        pending: list[CrashEvent] = []
        for event in self.store.iter_events():
            if event.triage_state == "pending":
                pending.append(event)
        lines = [INDEX_HEADER]
        lines.append("## Backlog (pinned)\n")
        items = self.backlog_items()
        if not items:
            lines.append("_empty_\n")
        for item in items:
            lines.append(f"- `{item.get('id')}` {item.get('exe')} ({item.get('severity')}) — {item.get('reason')}")
        lines.append("")
        lines.append("## Pending\n")
        if not pending:
            lines.append("_empty_\n")
        for event in pending:
            lines.append(f"- `{event.id}` {event.exe} ({event.severity}) at {event.time}")
        lines.append("")
        index = self.path / "INDEX.md"
        index.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return index

    # -- batch helper ------------------------------------------------------
    def batch_dir_for(self, event: CrashEvent) -> Path:
        date_str = parse_time(event.time).strftime("%Y-%m-%d")
        return self.store.batch_dir(date_str, Path(event.exe).name or "crash")

    def note_marker(self, event: CrashEvent) -> str:
        """A stable, timestamped marker used in notes/agent prompts."""
        return f"{event.id} @ {iso(utcnow())}"