"""Severity classification and triage for crash events.

Implements design draft section 7 (severity levels and escalation/downgrade
rules) as pure functions so the policy is testable without systemd, coredumpctl
or a running desktop session.

Judgement order, top to bottom, first hit wins:

* **S0** — core component (systemd, dbus, X, desktop shells/compositors, mesa,
  pipewire, NetworkManager, display managers, polkit, pacman, btrfs-progs, ...)
  or driver-related (backtrace hits a GPU/driver library, or the crashing
  package is itself a graphics driver).
* **S1** — a Linxira-authored component (``pkgRepo == linxira``).
* **S2** — everything else; ignored by default unless escalated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

S0, S1, S2 = "S0", "S1", "S2"
SEVERITIES = (S0, S1, S2)

PIN, IGNORE = "pin", "ignore"
DISPOSITIONS = (PIN, IGNORE)

REASON_AUTO_CORE = "auto-core"
REASON_AUTO_DRIVER = "auto-driver"
REASON_AUTO_LINXIRA = "auto-linxira"
REASON_AUTO_USER = "auto-user"
REASON_USER_PIN = "user-pin"
REASON_MUTE = "mute"
REASON_DEDUPE = "dedupe"
REASONS = (
    REASON_AUTO_CORE,
    REASON_AUTO_DRIVER,
    REASON_AUTO_LINXIRA,
    REASON_AUTO_USER,
    REASON_USER_PIN,
    REASON_MUTE,
    REASON_DEDUPE,
)

# Packages whose crash touches the OS core.
CORE_PACKAGES = frozenset(
    name.lower()
    for name in (
        "systemd",
        "systemd-libs",
        "dbus",
        "dbus-broker",
        "xorg-server",
        "xorg-server-common",
        "xwayland",
        "plasma-workspace",
        "kwin",
        "gnome-shell",
        "mutter",
        "cosmic-comp",
        "cosmic-session",
        "mesa",
        "lib32-mesa",
        "pipewire",
        "wireplumber",
        "networkmanager",
        "sddm",
        "gdm",
        "polkit",
        "pacman",
        "btrfs-progs",
    )
)

# Executables that identify a core component even before package lookup.
CORE_EXES = frozenset(
    name.lower()
    for name in (
        "systemd",
        "systemd-journald",
        "systemd-logind",
        "systemd-udevd",
        "systemd-resolved",
        "dbus-daemon",
        "dbus-broker",
        "xorg",
        "xwayland",
        "kwin_wayland",
        "kwin_x11",
        "plasmashell",
        "gnome-shell",
        "mutter",
        "cosmic-comp",
        "cosmic-session",
        "pipewire",
        "wireplumber",
        "networkmanager",
        "sddm",
        "gdm",
        "polkitd",
    )
)

# Graphics-driver packages: a crash inside one of these is driver-related.
GPU_DRIVER_PACKAGES = frozenset(
    name.lower()
    for name in (
        "nvidia",
        "nvidia-dkms",
        "nvidia-open",
        "nvidia-open-dkms",
        "nvidia-utils",
        "nvidia-lts",
        "xf86-video-amdgpu",
        "xf86-video-intel",
        "xf86-video-nouveau",
        "vulkan-radeon",
        "vulkan-intel",
        "vulkan-nouveau",
        "libva-mesa-driver",
    )
)

# Driver/graphics libraries that, when present in a backtrace, mark a crash as
# driver-related even for otherwise ordinary user software.
DRIVER_LIB_RE = re.compile(
    r"(libGL\b|libGLX|libEGL|libvulkan|nvidia|amdgpu|radeonsi|i915|nouveau|libdrm|libgbm)",
    re.IGNORECASE,
)

# Packages on a critical path: login session, package manager, filesystem tools.
KEY_PATH_PACKAGES = frozenset(
    name.lower()
    for name in (
        "pacman",
        "libalpm",
        "btrfs-progs",
        "systemd",
        "polkit",
        "sudo",
        "e2fsprogs",
        "xfsprogs",
        "util-linux",
        "cryptsetup",
        "filesystem",
        "grub",
        "plymouth",
        "sddm",
        "gdm",
        "networkmanager",
    )
)


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _basename(exe: object) -> str:
    return _norm(exe).rsplit("/", 1)[-1]


def is_core_component(exe: object = None, pkg: object = None, pkg_group=()) -> bool:
    """True when the crash belongs to a core system component."""
    if _norm(pkg) in CORE_PACKAGES:
        return True
    if _basename(exe) in CORE_EXES:
        return True
    groups = {_norm(group) for group in (pkg_group or ())}
    return "plasma" in groups or "gnome" in groups or "cosmic" in groups


def is_gpu_driver_package(pkg: object) -> bool:
    return _norm(pkg) in GPU_DRIVER_PACKAGES


def driver_library_hit(backtrace: str) -> str | None:
    """Return the first driver library name found in a backtrace, else None."""
    match = DRIVER_LIB_RE.search(backtrace or "")
    return match.group(0) if match else None


def is_driver_related(
    exe: object = None,
    pkg: object = None,
    backtrace: str = "",
    driver_hint: str | None = None,
) -> bool:
    if driver_hint:
        return True
    if is_gpu_driver_package(pkg):
        return True
    if driver_library_hit(backtrace):
        return True
    # A crashing process whose name is a driver module/kernel interface.
    return _basename(exe) in {"nvidia-smi", "amdgpu", "i915"}


def base_severity(
    *,
    exe: object = None,
    pkg: object = None,
    pkg_repo: object = None,
    pkg_group=(),
    driver_related: bool = False,
) -> str:
    """Classify an event into S0 / S1 / S2."""
    if driver_related or is_core_component(exe=exe, pkg=pkg, pkg_group=pkg_group):
        return S0
    if _norm(pkg_repo) == "linxira":
        return S1
    return S2


def is_key_path(pkg: object = None) -> bool:
    return _norm(pkg) in KEY_PATH_PACKAGES


@dataclass(frozen=True)
class TriageDecision:
    severity: str
    disposition: str  # PIN | IGNORE
    reason: str


def decide(
    *,
    severity: str,
    exe: object = None,
    pkg: object = None,
    repeat: int = 1,
    repeat_threshold: int = 3,
    driver_related: bool = False,
    learned: bool = False,
    muted: bool = False,
    already_pinned: bool = False,
    key_path: bool = False,
    driver_escalation: bool = True,
) -> TriageDecision:
    """Apply the design's disposition rules.

    Used both for the immediate decision and for the T0+timeout auto-triage
    (they share the same policy; timeout simply applies it without the user).
    """
    if muted:
        return TriageDecision(severity, IGNORE, REASON_MUTE)
    if already_pinned:
        return TriageDecision(severity, IGNORE, REASON_DEDUPE)

    if severity == S0:
        reason = REASON_AUTO_DRIVER if driver_related else REASON_AUTO_CORE
        return TriageDecision(severity, PIN, reason)
    if severity == S1:
        return TriageDecision(severity, PIN, REASON_AUTO_LINXIRA)

    # S2 — ordinary third-party / user software.
    if driver_related and driver_escalation:
        return TriageDecision(severity, PIN, REASON_AUTO_DRIVER)
    if repeat >= repeat_threshold:
        return TriageDecision(severity, PIN, REASON_AUTO_USER)
    if key_path:
        return TriageDecision(severity, PIN, REASON_AUTO_USER)
    if learned:
        return TriageDecision(severity, PIN, REASON_AUTO_USER)
    return TriageDecision(severity, IGNORE, REASON_AUTO_USER)