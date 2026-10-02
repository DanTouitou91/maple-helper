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
    a._before_kb_swap = lambda: app_cls._before_kb_swap(a)
    a.KB_SWAP_WAIT = app_cls.KB_SWAP_WAIT
    a.__dict__.setdefault("overlay", types.SimpleNamespace(busy=False, _syncing=False))
    return a


def brain(calls):
    return types.SimpleNamespace(shutdown=lambda: calls.append("shutdown"), stop_warm=lambda: calls.append("stop_warm"))


@pytest.mark.parametrize("result,toast", [(False, "Database is up to date"),
                                          (None, "Couldn't update the game database. We'll try again later.")])
def test_interactive_kb_update_tells_up_to_date_from_failed(app_cls, monkeypatch, result, toast):
    from maplehelper import updater
    calls = []
    monkeypatch.setattr(updater, "update_kb", lambda before_swap=None: calls.append(before_swap) or result)
    a = fake_app(app_cls, brain=brain(calls))
    app_cls.update_kb_interactive(a)
    assert a.done.wait(5) and a.toasts == [toast]
    assert len(calls) == 1 and callable(calls[0])       # the warm AI is only stopped right before a swap


def test_interactive_kb_update_reloads_and_shows_what_changed(app_cls, monkeypatch):
    from maplehelper import updater
    order = []

    def update(before_swap=None):
        before_swap()
        return True
    monkeypatch.setattr(updater, "update_kb", update)
    a = fake_app(app_cls, brain=brain(order))
    a.reload_kb = lambda: order.append("reload")
    a.kb_updated = lambda before, interactive=False: (order.append(("notes", interactive)), a.done.set())
    app_cls.update_kb_interactive(a)
    assert a.done.wait(5) and order == ["stop_warm", "reload", ("notes", True)]


def test_kb_swap_waits_for_the_answer_in_progress(app_cls, monkeypatch):
    """The download can take minutes: an answer asked meanwhile is never killed by the swap."""
    calls = []
    a = fake_app(app_cls, brain=brain(calls), overlay=types.SimpleNamespace(busy=True, _syncing=False))
    threading.Timer(0.7, lambda: setattr(a.overlay, "busy", False)).start()
    assert app_cls._before_kb_swap(a) is True and calls == ["stop_warm"]      # after the answer, the warm one only

    a.overlay._syncing, a.KB_SWAP_WAIT = True, 0.6          # a screenshot read that doesn't end in time
    calls.clear()
    assert app_cls._before_kb_swap(a) is False and calls == []                # the swap waits for the next check


def test_one_kb_update_at_a_time(app_cls, monkeypatch):
    from maplehelper import updater
    gate, started = threading.Event(), []

    def slow(before_swap=None):
        started.append(1)
        gate.wait(5)
        return False
    monkeypatch.setattr(updater, "update_kb", slow)
    a = fake_app(app_cls, brain=brain([]))
    app_cls.update_kb_interactive(a)
    app_cls.update_kb_interactive(a)          # a second click while the first still downloads
    assert a.toasts == ["Already checking for a database update…"]      # said, not silently ignored
    a.done.clear()
    gate.set()
    assert a.done.wait(5) and started == [1] and a.toasts[-1] == "Database is up to date"


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


def test_session_summaries_off_keep_the_chat_off_the_ai(app_cls, monkeypatch):
    import maplehelper.app as app_mod
    sent, kept, done = [], [], threading.Event()

    class History:
        def __init__(self, cid):
            pass

        def add_summary(self, s):
            kept.append(s)
            done.set()
    monkeypatch.setattr(app_mod, "History", History)
    a = fake_app(app_cls, profiles=types.SimpleNamespace(active=types.SimpleNamespace(id="c1")),
                 brain=types.SimpleNamespace(summarize=lambda text: sent.append(text) or "memo"))
    ended = []
    a.overlay = types.SimpleNamespace(isVisible=lambda: False,
                                      end_session=lambda: (ended.append(1), "user: hi\nassistant: hey")[1])
    a.settings = {"language": "en", "session_summaries": False}
    app_cls.summarize_session(a)
    assert ended == [1] and not sent            # the session still ends locally; nothing goes to the AI
    a.settings["session_summaries"] = True
    app_cls.summarize_session(a)
    assert done.wait(5) and sent == ["user: hi\nassistant: hey"] and kept == ["memo"]


def test_session_summaries_default_on(isolated_store):
    assert isolated_store.Settings()["session_summaries"] is True
