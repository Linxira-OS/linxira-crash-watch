from __future__ import annotations

from linxira_crash_watch import notify


def test_build_argv_has_actions():
    argv = notify.build_argv("title", "body")
    assert argv[0] == "notify-send"
    assert any(a.startswith("--action=investigate=") for a in argv)
    assert any(a.startswith("--action=pin=") for a in argv)
    assert any(a.startswith("--action=mute=") for a in argv)
    assert argv[-2:] == ["title", "body"]


def test_crash_summary_includes_severity_and_package():
    class E:
        exe = "/usr/bin/kwin_wayland"
        severity = "S0"
        signal = "SIGSEGV"
        pkg = "kwin"
        driver_hint = None

    title, body = notify.crash_summary(E())
    assert "kwin_wayland" in title
    assert "S0" in title
    assert "kwin" in body


class DummyRun:
    def __init__(self, stdout: str):
        self.stdout = stdout

    def __call__(self, argv, **_kwargs):
        assert argv[0] == "notify-send"
        return type("C", (), {"stdout": self.stdout, "returncode": 0})()


def test_notify_returns_selected_action(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda _name: "/usr/bin/notify-send")
    result = notify.notify("t", "b", runner=DummyRun("pin"))
    assert result.sent is True
    assert result.action == "pin"


def test_notify_noop_without_daemon(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda _name: None)
    result = notify.notify("t", "b")
    assert result.sent is False
    assert result.action is None

def test_build_argv_has_copy_action():
    argv = notify.build_argv("title", "body")
    assert any(a.startswith("--action=copy=") for a in argv)


def test_copy_to_clipboard_uses_first_available_tool(monkeypatch):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs.get("input")))
        return type("C", (), {"returncode": 0})()

    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/wl-copy" if name == "wl-copy" else None)
    assert notify.copy_to_clipboard("hello", runner=runner) is True
    assert calls == [(("wl-copy",), "hello")]


def test_copy_to_clipboard_without_backend(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda _name: None)
    assert notify.copy_to_clipboard("hello") is False
