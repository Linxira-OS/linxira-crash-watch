"""linxira-crash-watch — crash capture, triage, and user-approved agent wake-up.

The package never talks to the agent on its own: capture, notification, and
timeout triage all run at zero token cost. Only an explicit user action launches
``zetacode`` in the debug workspace.
"""
from __future__ import annotations

from importlib import metadata

PACKAGE = "linxira-crash-watch"
CLI_NAME = "linxira-crash"
# Registered command provided by packages/packages/linxira-zeta-c-bin
# (provides=('zetacode'), installs /usr/bin/zetacode).
ZETACODE = "zetacode"
SCHEMA = "org.linxira.crash-event.v1"

__all__ = ["PACKAGE", "CLI_NAME", "ZETACODE", "SCHEMA", "version"]


def version() -> str:
    """Return the installed distribution version, or a dev marker."""
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        return "0.0.0+unknown"