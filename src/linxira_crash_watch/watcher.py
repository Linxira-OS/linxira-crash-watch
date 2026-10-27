"""The crash watcher.

Polls ``systemd-coredump`` (via ``coredumpctl``), turns new dumps into crash
events, classifies them, notifies the user, and — when a notification goes
unanswered past the timeout — applies the level-based auto-triage. It never
launches the agent: that only happens on an explicit user action.

All external commands use a fixed argument vector (no shell). Parsers are split
out as pure functions so the policy is tested without systemd present.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time as _time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from . import notify as notify_mod
from . import prompts
from . import triage
from .about import CLI_NAME
from .config import Config, state_dir
from .events import (
    STATE_IGNORED,
    STATE_PENDING,
    STATE_PINNED,
    CrashEvent,
    iso,
    parse_time,
    utcnow,
)
from .workspace import DEDUPE_WINDOW, Workspace

COREDUMPCTL = "coredumpctl"
PACMAN = "pacman"
DEFAULT_INTERVAL = 60
DEFAULT_SINCE = "-1h"
SEEN_LIMIT = 2000

_SIGNALS = {
    3: "SIGQUIT",
    4: "SIGILL",
    6: "SIGABRT",
    7: "SIGBUS",
    8: "SIGFPE",
    9: "SIGKILL",
    11: "SIGSEGV",
    15: "SIGTERM",
}

_REPO_RE = re.compile(r"^Repository\s*:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_GROUPS_RE = re.compile(r"^Groups\s*:\s*(?P<value>.+?)\s*$", re.MULTILINE)


@dataclass
class CoredumpRecord:
    pid: int
    exe: str
    signal: str
    time: str
    dump_ref: str | None = None
    comm: str | None = None

    @property
    def dedup_key(self) -> str:
        return f"{self.pid}:{self.time}:{self.signal}"


def signal_name(value: object) -> str:
    if isinstance(value, int):
        return _SIGNALS.get(value, f"SIG{value}")
    text = str(value or "").strip()
    if text.isdigit():
        return _SIGNALS.get(int(text), f"SIG{text}")
    return text or "UNKNOWN"


def parse_coredumpctl_json(text: str) -> list[CoredumpRecord]:
    """Parse ``coredumpctl list --json`` output into records (tolerant)."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    records: list[CoredumpRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pid = item.get("pid", item.get("PID", 0))
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            pid = 0
        exe = item.get("exe") or item.get("comm") or item.get("_EXE") or ""
        when = item.get("timestamp") or item.get("time") or item.get("_SOURCE_REALTIME_TIMESTAMP") or ""
        dump_ref = item.get("coredump") or item.get("coredump_ref")
        records.append(
            CoredumpRecord(
                pid=pid,
                exe=str(exe),
                signal=signal_name(item.get("signal", item.get("sig", "UNKNOWN"))),
                time=str(when),
                dump_ref=str(dump_ref) if dump_ref else None,
                comm=item.get("comm"),
            )
        )
    return records


def parse_pacman_qi(text: str) -> tuple[str | None, tuple[str, ...]]:
    """Extract (repository, groups) from ``pacman -Qi`` output."""
    repo_match = _REPO_RE.search(text or "")
    groups_match = _GROUPS_RE.search(text or "")
    repo = repo_match.group("value") if repo_match else None
    groups: tuple[str, ...] = ()
    if groups_match:
        raw = groups_match.group("value")
        if raw and raw.lower() != "none":
            groups = tuple(part.strip() for part in raw.split() if part.strip())
    return repo, groups


def normalize_repo(repo: str | None) -> str | None:
    if not repo:
        return None
    return "linxira" if repo.strip().lower() == "linxira" else repo.strip().lower()


def _check_arg(value: str) -> str:
    """Guard against option-injection via a positional argument."""
    if value.startswith("-"):
        raise ValueError(f"unexpected option-like argument: {value!r}")
    return value


class Watcher:
    def __init__(self, config: Config, workspace: Workspace, runner=subprocess.run):
        self.config = config
        self.workspace = workspace
        self.runner = runner
        self.state_dir = state_dir()

    # -- external helpers --------------------------------------------------
    def _run(self, argv: list[str], timeout: int = 20) -> str | None:
        try:
            completed = self.runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if getattr(completed, "returncode", 0) != 0:
            return None
        return completed.stdout or ""

    def collect(self, since: str = DEFAULT_SINCE) -> list[CoredumpRecord]:
        text = self._run([COREDUMPCTL, "list", "--json=short", f"--since={since}"])
        if text is None:
            return []
        return parse_coredumpctl_json(text)

    def package_of(self, exe: str) -> str | None:
        text = self._run([PACMAN, "-Qoq", _check_arg(exe)])
        if not text:
            return None
        first = text.strip().splitlines()[0].strip()
        return first or None

    def package_meta(self, pkg: str) -> tuple[str | None, tuple[str, ...]]:
        text = self._run([PACMAN, "-Qi", _check_arg(pkg)])
        return parse_pacman_qi(text or "")

    def backtrace_of(self, pid: int) -> str:
        return self._run([COREDUMPCTL, "info", "--no-pager", str(pid)], timeout=30) or ""

    # -- seen ledger -------------------------------------------------------
    def _seen_path(self) -> Path:
        return self.state_dir / "seen.json"

    def _load_seen(self) -> list[str]:
        path = self._seen_path()
        if not path.is_file():
            return []
        try:
            return list(json.loads(path.read_text(encoding="utf-8")).get("keys", []))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_seen(self, keys: list[str]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        trimmed = keys[-SEEN_LIMIT:]
        self._seen_path().write_text(
            json.dumps({"keys": trimmed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # -- event construction -----------------------------------------------
    def _next_id(self, date_str: str) -> str:
        prefix = f"e-{date_str}-"
        highest = 0
        for event in self.workspace.store.iter_events():
            if event.id.startswith(prefix):
                try:
                    highest = max(highest, int(event.id[len(prefix):]))
                except ValueError:
                    continue
        return f"{prefix}{highest + 1:04d}"

    def build_event(self, record: CoredumpRecord, now=None) -> CrashEvent:
        now = now or utcnow()
        exe = record.exe or "unknown"
        pkg = self.package_of(exe) if exe else None
        repo, groups = self.package_meta(pkg) if pkg else (None, ())
        repo = normalize_repo(repo)

        backtrace = self.backtrace_of(record.pid) if record.pid else ""
        driver_hint = triage.driver_library_hit(backtrace)
        driver_related = triage.is_driver_related(exe=exe, pkg=pkg, backtrace=backtrace, driver_hint=driver_hint)

        repeat = self.workspace.repeat_count(exe, now=now)
        severity = triage.base_severity(
            exe=exe, pkg=pkg, pkg_repo=repo, pkg_group=groups, driver_related=driver_related
        )

        date_str = now.strftime("%Y-%m-%d")
        return CrashEvent(
            id=self._next_id(date_str),
            time=iso(now),
            exe=exe,
            pid=record.pid,
            signal=record.signal,
            scope="system",
            pkg=pkg,
            pkg_repo=repo,
            pkg_group=groups,
            driver_related=driver_related,
            driver_hint=driver_hint,
            repeat=repeat,
            severity=severity,
            triage_state=STATE_PENDING,
            triage_reason=None,
            triage_at=None,
            dump_ref=f"coredumpctl:{record.dump_ref or record.pid}",
        )

    # -- main loop ---------------------------------------------------------
    def poll_once(self, now=None) -> list[CrashEvent]:
        """Collect new dumps, persist events, and notify. Zero token."""
        now = now or utcnow()
        seen = self._load_seen()
        seen_set = set(seen)
        created: list[CrashEvent] = []
        for record in self.collect():
            if record.dedup_key in seen_set:
                continue
            seen.append(record.dedup_key)
            seen_set.add(record.dedup_key)
            event = self.build_event(record, now=now)
            if self.workspace.is_muted(event.exe):
                event.triage_state = STATE_IGNORED
                event.triage_reason = triage.REASON_MUTE
                event.triage_at = iso(now)
            self.workspace.store.save(event)
            if event.triage_state == STATE_PENDING:
                title, body = notify_mod.crash_summary(event)
                result = notify_mod.notify(title, body)
                self._apply_notification_action(event, result.action)
            created.append(event)
        self._save_seen(seen)
        if created:
            self.workspace.write_index()
        return created

    def _apply_notification_action(self, event: CrashEvent, action: str | None) -> None:
        """Apply the action the user picked on the crash notification.

        All effects stay local and explicit: pin/mute update the workspace,
        copy writes the ready-to-paste zetacode command to the clipboard, and
        investigate launches the same CLI path the user would run by hand.
        """
        if not action:
            return
        now = utcnow()
        if action == notify_mod.ACTION_PIN:
            updated = self.workspace.store.update_triage(
                event.id, STATE_PINNED, triage.REASON_USER_PIN, iso(now)
            )
            self.workspace.pin_to_backlog(updated)
        elif action == notify_mod.ACTION_MUTE:
            self.workspace.add_mute(event.exe)
            self.workspace.store.update_triage(
                event.id, STATE_IGNORED, triage.REASON_MUTE, iso(now)
            )
        elif action == notify_mod.ACTION_COPY:
            found = self.workspace.store.find(event.id)
            if found:
                notify_mod.copy_to_clipboard(
                    prompts.command_text(self.workspace.path, found[1])
                )
        elif action == notify_mod.ACTION_INVESTIGATE:
            self._launch_investigate(event)
        if action in (
            notify_mod.ACTION_PIN,
            notify_mod.ACTION_MUTE,
            notify_mod.ACTION_INVESTIGATE,
        ):
            self.workspace.write_index()

    def _launch_investigate(self, event: CrashEvent) -> None:
        executable = shutil.which(CLI_NAME)
        if executable:
            argv = [executable, "investigate", event.id]
        else:
            argv = [sys.executable, "-m", "linxira_crash_watch.cli", "investigate", event.id]
        try:
            subprocess.Popen(argv, start_new_session=True)
        except (OSError, subprocess.SubprocessError):
            return

    def sweep_timeouts(self, now=None) -> list[CrashEvent]:
        """Auto-triage pending events past the timeout. Zero token."""
        now = now or utcnow()
        timeout = timedelta(seconds=self.config.timeout_seconds)
        acted: list[CrashEvent] = []
        for event in list(self.workspace.store.iter_events()):
            if event.triage_state != STATE_PENDING:
                continue
            try:
                when = parse_time(event.time)
            except (ValueError, TypeError):
                continue
            if (now - when) < timeout:
                continue
            decision = triage.decide(
                severity=event.severity,
                exe=event.exe,
                pkg=event.pkg,
                repeat=event.repeat,
                repeat_threshold=self.config.repeat_threshold,
                driver_related=event.driver_related,
                learned=self.workspace.backlog_has_exe(event.exe),
                already_pinned=self.workspace.backlog_has_exe(
                    event.exe, within=DEDUPE_WINDOW, now=now
                ),
                muted=self.workspace.is_muted(event.exe),
                key_path=triage.is_key_path(event.pkg),
                driver_escalation=self.config.driver_related_escalation,
            )
            state = STATE_PINNED if decision.disposition == triage.PIN else STATE_IGNORED
            updated = self.workspace.store.update_triage(event.id, state, decision.reason, iso(now))
            if state == STATE_PINNED:
                self.workspace.pin_to_backlog(updated)
            acted.append(updated)
        if acted:
            self.workspace.write_index()
        return acted

    def run(self, interval: int = DEFAULT_INTERVAL, once: bool = False) -> None:
        self.workspace.ensure()
        while True:
            self.poll_once()
            self.sweep_timeouts()
            if once:
                return
            _time.sleep(interval)