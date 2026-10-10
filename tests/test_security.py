"""Hard-boundary checks: no privileged escalation, no shell, correct command name."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "linxira_crash_watch"

FORBIDDEN = [
    r"shell\s*=\s*True",
    r"os\.system\s*\(",
    r"subprocess\.getoutput\s*\(",
]

# Modules that build or launch commands.
LAUNCH_SOURCES = ("cli.py", "lanes.py", "watcher.py", "notify.py")
PRIVILEGE_TOKENS = ("sudo", "pkexec", "doas", "run0")


def read_sources() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(SRC.glob("*.py"))}


def test_no_forbidden_execution_patterns():
    for name, text in read_sources().items():
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text), f"{name} matches forbidden pattern {pattern!r}"


def test_launch_paths_never_escalate_privileges():
    for name in LAUNCH_SOURCES:
        text = (SRC / name).read_text(encoding="utf-8")
        for token in PRIVILEGE_TOKENS:
            assert f'"{token}"' not in text, f"{name} references privileged command {token!r}"
            assert f"'{token}'" not in text, f"{name} references privileged command {token!r}"


def test_agent_command_is_zetacode_only():
    text = (SRC / "about.py").read_text(encoding="utf-8")
    assert 'ZETACODE = "zetacode"' in text

    lanes_text = (SRC / "lanes.py").read_text(encoding="utf-8")
    # The only literal agent binary used in argv construction is zetacode.
    assert '"zeta"' not in lanes_text
    assert '"omp"' not in lanes_text


def test_unattended_default_disabled():
    config_text = (SRC / "config.py").read_text(encoding="utf-8")
    assert "DEFAULT_UNATTENDED_TOOLS = \"read,grep,glob,lsp\"" in config_text
    assert "enabled: bool = False" in config_text


def test_schema_stable():
    about_text = (SRC / "about.py").read_text(encoding="utf-8")
    assert 'SCHEMA = "org.linxira.crash-event.v1"' in about_text
    events_text = (SRC / "events.py").read_text(encoding="utf-8")
    assert 'SCHEMA = "org.linxira.crash-event.v1"' in events_text