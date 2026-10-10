"""Command-line interface: ``linxira-crash``.

Subcommands: ``status``, ``list``, ``pin``, ``ignore``, ``restore``, ``mute``,
``investigate``, and ``daemon``. Everything except ``investigate`` is zero-token
and works offline; ``investigate`` is the only path that launches ``zetacode``.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .about import CLI_NAME, version
from .config import Config, load_config
from .events import STATE_IGNORED, STATE_INVESTIGATED, STATE_PENDING, STATE_PINNED, iso, utcnow
from .lanes import LANE_INTERACTIVE, plan_lane
from .triage import REASON_USER_PIN
from .watcher import Watcher
from .workspace import Workspace

PROMPT = (
    "排查这批崩溃:先建立事实(backtrace、复现条件、是否驱动相关),"
    "再判断是否值得上报上游;只出结论,不改系统。"
)


def _workspace(config: Config) -> Workspace:
    return Workspace(config.workspace_path).ensure()


def _find(workspace: Workspace, event_id: str):
    found = workspace.store.find(event_id)
    if not found:
        print(f"error: no such event: {event_id}", file=sys.stderr)
        return None
    return found


# -- commands -------------------------------------------------------------
def cmd_status(config: Config) -> int:
    workspace = _workspace(config)
    counts = workspace.store.counts()
    print(f"workspace: {workspace.path}")
    print(f"timeout:   {config.timeout_seconds}s")
    print(f"unattended lane: {'on' if config.unattended.enabled else 'off'}")
    print(
        "events: pending={pending} pinned={pinned} ignored={ignored} investigated={investigated}".format(
            **counts
        )
    )
    return 0


def cmd_list(config: Config, state: str | None) -> int:
    workspace = _workspace(config)
    events = [e for e in workspace.store.iter_events() if state is None or e.triage_state == state]
    if not events:
        print("(no events)")
        return 0
    for event in events:
        name = Path(event.exe).name or event.exe
        print(f"{event.id}  {event.severity}  {event.triage_state:<12} {name}  {event.time}")
    return 0


def cmd_pin(config: Config, event_id: str) -> int:
    workspace = _workspace(config)
    found = _find(workspace, event_id)
    if not found:
        return 1
    event = workspace.store.update_triage(event_id, STATE_PINNED, REASON_USER_PIN, iso(utcnow()))
    workspace.pin_to_backlog(event)
    workspace.write_index()
    print(f"pinned {event_id} -> backlog")
    return 0


def cmd_ignore(config: Config, event_id: str, reason: str | None) -> int:
    workspace = _workspace(config)
    if not _find(workspace, event_id):
        return 1
    workspace.store.update_triage(event_id, STATE_IGNORED, reason or "auto-user", iso(utcnow()))
    workspace.remove_from_backlog(event_id)
    workspace.write_index()
    print(f"ignored {event_id}")
    return 0


def cmd_restore(config: Config, event_id: str) -> int:
    workspace = _workspace(config)
    if not _find(workspace, event_id):
        return 1
    workspace.store.update_triage(event_id, STATE_PENDING, None, None)
    workspace.remove_from_backlog(event_id)
    workspace.write_index()
    print(f"restored {event_id} -> pending")
    return 0


def cmd_mute(config: Config, program: str | None, off: bool, list_only: bool) -> int:
    workspace = _workspace(config)
    if list_only:
        for name in workspace.mute_list():
            print(name)
        return 0
    if not program:
        print("error: mute requires a program name (or --list)", file=sys.stderr)
        return 2
    if off:
        workspace.remove_mute(program)
        print(f"unmuted {program}")
    else:
        workspace.add_mute(program)
        print(f"muted {program}")
    return 0


def cmd_investigate(config: Config, event_id: str, dry_run: bool) -> int:
    workspace = _workspace(config)
    found = _find(workspace, event_id)
    if not found:
        return 1
    _, path = found
    command = plan_lane(
        LANE_INTERACTIVE,
        str(workspace.path),
        PROMPT,
        evidence=str(path),
        unattended_enabled=config.unattended.enabled,
    )
    print(f"launching: {command.display}")
    if dry_run:
        return 0
    try:
        subprocess.Popen(command.argv)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"error: could not launch agent: {exc}", file=sys.stderr)
        return 1
    workspace.store.update_triage(event_id, STATE_INVESTIGATED, "user-investigate", iso(utcnow()))
    return 0


def cmd_daemon(config: Config, interval: int, once: bool) -> int:
    Watcher(config, _workspace(config)).run(interval=interval, once=once)
    return 0


# -- parser ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=CLI_NAME, description="Crash capture, triage, and user-approved agent wake-up.")
    parser.add_argument("--version", action="version", version=f"{CLI_NAME} {version()}")
    parser.add_argument("--config", type=Path, default=None, help="path to crash-watch.toml")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="show workspace, config, and event counts")

    p_list = sub.add_parser("list", help="list crash events")
    p_list.add_argument("--state", choices=[STATE_PENDING, STATE_PINNED, STATE_IGNORED, STATE_INVESTIGATED])

    p_pin = sub.add_parser("pin", help="pin an event into the backlog (0 token)")
    p_pin.add_argument("id")

    p_ignore = sub.add_parser("ignore", help="ignore an event (0 token)")
    p_ignore.add_argument("id")
    p_ignore.add_argument("--reason", default=None)

    p_restore = sub.add_parser("restore", help="restore an ignored/pinned event to pending")
    p_restore.add_argument("id")

    p_mute = sub.add_parser("mute", help="mute/unmute a program, or list muted programs")
    p_mute.add_argument("program", nargs="?")
    p_mute.add_argument("--off", action="store_true", help="unmute the program")
    p_mute.add_argument("--list", action="store_true", dest="list_only")

    p_inv = sub.add_parser("investigate", help="launch zetacode on an event (spends tokens)")
    p_inv.add_argument("id")
    p_inv.add_argument("--dry-run", action="store_true")

    p_daemon = sub.add_parser("daemon", help="run the watcher loop")
    p_daemon.add_argument("--interval", type=int, default=60)
    p_daemon.add_argument("--once", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "status":
        return cmd_status(config)
    if args.command == "list":
        return cmd_list(config, args.state)
    if args.command == "pin":
        return cmd_pin(config, args.id)
    if args.command == "ignore":
        return cmd_ignore(config, args.id, args.reason)
    if args.command == "restore":
        return cmd_restore(config, args.id)
    if args.command == "mute":
        return cmd_mute(config, args.program, args.off, args.list_only)
    if args.command == "investigate":
        return cmd_investigate(config, args.id, args.dry_run)
    if args.command == "daemon":
        return cmd_daemon(config, args.interval, args.once)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())