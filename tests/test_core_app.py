"""App glue that runs off the GUI thread: KB updates and the problem report (no real window, network or CLI)."""
import sys
import threading
import types

import pytest


@pytest.fixture
def app_cls(monkeypatch):
    # the OS layer needs Windows or macOS; these code paths never touch it
    fake = types.ModuleType("maplehelper.osapi")
    fake.IS_MAC = False
    monkeypatch.setitem(sys.modules, "maplehelper.osapi", fake)
    from maplehelper import app
    return app.MapleHelperApp


def fake_app(app_cls, **kw):
    a = types.SimpleNamespace(settings={"language": "en", "provider": "claude"}, toasts=[], done=threading.Event(),
                              main_thread=types.SimpleNamespace(call=types.SimpleNamespace(emit=lambda fn: fn())),
                              **kw)
    a.toast = lambda title, message="", timeout_ms=5000: (a.toasts.append(title), a.done.set())
    a._update_kb = lambda finished: app_cls._update_kb(a, finished)
    return a


@pytest.mark.parametrize("result,toast", [(False, "Database is up to date"),
                                          (None, "Couldn't update the game database. We'll try again later.")])
def test_interactive_kb_update_tells_up_to_date_from_failed(app_cls, monkeypatch, result, toast):
    from maplehelper import updater
    calls = []
    monkeypatch.setattr(updater, "update_kb", lambda before_swap=None: calls.append(before_swap) or result)
    a = fake_app(app_cls, brain=types.SimpleNamespace(shutdown=lambda: calls.append("shutdown")))
    app_cls.update_kb_interactive(a)
    assert a.done.wait(5) and a.toasts == [toast]
    assert "shutdown" not in calls            # the warm AI is only stopped right before a swap


def test_interactive_kb_update_reloads_and_shows_what_changed(app_cls, monkeypatch):
    from maplehelper import updater
    order = []

    def update(before_swap=None):
        before_swap()
        return True
    monkeypatch.setattr(updater, "update_kb", update)
    a = fake_app(app_cls, brain=types.SimpleNamespace(shutdown=lambda: order.append("shutdown")))
    a.reload_kb = lambda: order.append("reload")
    a.kb_updated = lambda before, interactive=False: (order.append(("notes", interactive)), a.done.set())
    app_cls.update_kb_interactive(a)
    assert a.done.wait(5) and order == ["shutdown", "reload", ("notes", True)]


def test_one_kb_update_at_a_time(app_cls, monkeypatch):
    from maplehelper import updater
    gate, started = threading.Event(), []

    def slow(before_swap=None):
        started.append(1)
        gate.wait(5)
        return False
    monkeypatch.setattr(updater, "update_kb", slow)
    a = fake_app(app_cls, brain=types.SimpleNamespace(shutdown=lambda: None))
    app_cls.update_kb_interactive(a)
    app_cls.update_kb_interactive(a)          # a second click while the first still downloads
    gate.set()
    assert a.done.wait(5) and started == [1]


def test_problem_report_reads_the_sign_in_status_off_the_gui_thread(app_cls, monkeypatch, tmp_path):
    import subprocess

    from maplehelper import providers, report
    gui = threading.current_thread()
    seen = {}

    def status():
        seen["thread"] = threading.current_thread()
        return "ok"
    monkeypatch.setattr(providers.get("claude"), "status", status)
    monkeypatch.setattr(report, "system_info", lambda *a: {"ai": a[-1]})
    monkeypatch.setattr(report, "build_report", lambda folder, info, settings: seen.update(info) or tmp_path / "r.zip")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)     # "show the file" in Explorer / Finder

    class Settings(dict):
        data = {}
    a = fake_app(app_cls)
    a.settings = Settings(language="en", provider="claude", no_ai=False)
    app_cls.make_report(a)
    assert a.done.wait(5) and seen["thread"] is not gui and seen["ai"] == "Claude: ok"
