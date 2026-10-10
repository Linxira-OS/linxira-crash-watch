"""linxira-crash-watch — see about.py and the design draft in document/."""
from __future__ import annotations

from .about import CLI_NAME, PACKAGE, SCHEMA, ZETACODE, version

__all__ = ["CLI_NAME", "PACKAGE", "SCHEMA", "ZETACODE", "version"]
__version__ = version()