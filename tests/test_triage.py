from __future__ import annotations

from linxira_crash_watch import triage


def test_core_component_by_package():
    assert triage.is_core_component(pkg="systemd")
    assert triage.is_core_component(pkg="kwin")
    assert triage.is_core_component(exe="/usr/bin/kwin_wayland")
    assert triage.is_core_component(pkg="acme", pkg_group=["plasma"])


def test_driver_library_detection():
    assert triage.driver_library_hit("... libEGL.so.1 ...") == "libEGL"
    assert triage.driver_library_hit("nvidia kernel module") == "nvidia"
    assert triage.driver_library_hit("plain backtrace") is None


def test_base_severity():
    assert triage.base_severity(pkg="systemd") == triage.S0
    assert triage.base_severity(pkg="foo", pkg_repo="extra", driver_related=True) == triage.S0
    assert triage.base_severity(pkg="linxira-update", pkg_repo="linxira") == triage.S1
    assert triage.base_severity(pkg="foo", pkg_repo="extra") == triage.S2


def test_decide_core_and_linxira_pin():
    core = triage.decide(severity=triage.S0)
    assert core.disposition == triage.PIN
    assert core.reason == triage.REASON_AUTO_CORE

    driver = triage.decide(severity=triage.S0, driver_related=True)
    assert driver.reason == triage.REASON_AUTO_DRIVER

    own = triage.decide(severity=triage.S1)
    assert own.disposition == triage.PIN
    assert own.reason == triage.REASON_AUTO_LINXIRA


def test_decide_s2_default_ignore():
    decision = triage.decide(severity=triage.S2, repeat=1, repeat_threshold=3)
    assert decision.disposition == triage.IGNORE


def test_decide_s2_escalations():
    assert triage.decide(severity=triage.S2, repeat=3, repeat_threshold=3).disposition == triage.PIN
    assert triage.decide(severity=triage.S2, key_path=True).disposition == triage.PIN
    assert triage.decide(severity=triage.S2, learned=True).disposition == triage.PIN
    assert triage.decide(severity=triage.S2, driver_related=True).disposition == triage.PIN


def test_decide_downgrades():
    muted = triage.decide(severity=triage.S0, muted=True)
    assert muted.disposition == triage.IGNORE
    assert muted.reason == triage.REASON_MUTE

    dedupe = triage.decide(severity=triage.S0, already_pinned=True)
    assert dedupe.disposition == triage.IGNORE
    assert dedupe.reason == triage.REASON_DEDUPE


def test_driver_escalation_can_be_disabled():
    decision = triage.decide(severity=triage.S2, driver_related=True, driver_escalation=False)
    assert decision.disposition == triage.IGNORE