"""Using the app without an AI: nothing runs a CLI, onboarding can skip the AI, Settings can connect it later
(offscreen Qt, no real CLI, network or OS layer)."""
import os
import subprocess
import sys
import threading
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


def _stub_osapi():
    """winapi needs Windows: elsewhere the app runs against a stand-in OS layer (no game, no hotkeys)."""
    from PySide6.QtCore import QObject, Signal

    class Hotkeys(QObject):
        pressed = Signal(int)

        def register(self, *a):
            return True

        def unregister(self, *a):
            pass

        def close(self):
            pass
    stub = types.ModuleType("maplehelper.osapi")
    stub.IS_MAC = False
    stub.SCREEN_COORDS_ARE_PHYSICAL = False
    stub.Hotkeys = Hotkeys
    for name in ("find_game_window", "capture_game", "window_rect", "float_over_fullscreen", "activate_self",
                 "focus_window", "set_autostart", "missing_permissions", "prepare_process"):
        setattr(stub, name, lambda *a, **k: None)
    return stub


OSAPI = _stub_osapi()
try:
    import maplehelper.osapi  # noqa: F401
except (AttributeError, ImportError):
    sys.modules["maplehelper.osapi"] = OSAPI
    import maplehelper
    maplehelper.osapi = OSAPI


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def no_spawn(monkeypatch):
    """Every process start is recorded (and refused): no AI CLI may run."""
    spawned = []

    def refuse(*a, **k):
        spawned.append(a[0] if a else k.get("args"))
        raise OSError("no process may start in this test")
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    return spawned


@pytest.fixture
def asked(monkeypatch):
    """Every sign-in / usage / model check of either provider is recorded (on the shared provider objects:
    another test may have left an attribute there that a class-level patch wouldn't reach)."""
    from maplehelper import providers
    calls = []
    for p in providers.PROVIDERS.values():
        monkeypatch.setattr(p, "account", lambda n=p.name: calls.append(("account", n)) or
                            {"status": "ok", "email": None, "method": None})
        monkeypatch.setattr(p, "status", lambda n=p.name: calls.append(("account", n)) or "ok")
        monkeypatch.setattr(p, "read_limits", lambda *a, n=p.name, **k: calls.append(("limits", n)))
    # Claude's model list is fixed; ChatGPT's is asked from its CLI
    monkeypatch.setattr(providers.get("codex"), "models", lambda: calls.append(("models", "codex")) or [(None, "")])
    return calls


def pump(qapp, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


# ---------------------------------------------------------------- brain

def test_ask_without_an_ai_answers_no_ai_and_starts_nothing(kb, no_spawn):
    from maplehelper.brain import Brain
    for provider in ("claude", "codex"):
        b = Brain(kb, provider=provider)
        b.backend.exe = "/usr/bin/" + provider       # installed, even: still never started
        b.no_ai = True
        assert b.ask("which map should I train in?", None, None, b"jpeg").error == "no_ai"
        b.prewarm()
        assert b.summarize("player: hi\nassistant: hello") is None
        assert not b.available()
    assert no_spawn == []


def test_the_chat_shows_an_unknown_error_code_as_a_plain_message(qapp, isolated_store, kb):
    """no_ai reaches the chat like any error: a message, no crash (the chat adds its own wording for it)."""
    from maplehelper.brain import Answer
    from maplehelper.ui.overlay import Overlay
    s = isolated_store.Settings()
    s["language"], s["no_ai"] = "en", True
    ov = Overlay(s, isolated_store.Profiles(), kb, types.SimpleNamespace())
    ov._pending_bubble = ov.add_bubble("…", "assistant")
    ov.busy = True
    ov._on_done(Answer(error="no_ai"), None)
    assert not ov.busy
    ov.close()


# ---------------------------------------------------------------- onboarding

@pytest.fixture
def env(qapp, isolated_store, kb, monkeypatch):
    from maplehelper import providers
    checks = []
    monkeypatch.setattr(providers.get("claude"), "status", lambda: checks.append("claude") or "logged_out")
    s = isolated_store.Settings()
    s["language"] = "en"
    return s, isolated_store.Profiles(), kb, checks


def _fill_character(dlg):
    dlg.form.name.setText("Mapler")
    next(b for b in dlg.form.class_group.buttons() if b.property("cls") == "Beginner").setChecked(True)


def test_onboarding_is_language_then_character_then_an_optional_ai(env, qapp):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb, checks = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    assert dlg.pages == [dlg.lang_page, dlg.form.parentWidget(), dlg.ai_page, dlg.pages[-1]]
    dlg.show()
    pump(qapp, 0.1)
    assert checks == []                       # the AI's CLI is untouched until its page
    dlg._go_next()
    assert not dlg.next.isEnabled()          # the character is required
    _fill_character(dlg)
    dlg._go_next()
    assert dlg.stack.currentWidget() is dlg.ai_page
    pump(qapp)
    assert checks == ["claude"]
    assert not dlg.next.isEnabled() and dlg.later.isVisibleTo(dlg)
    dlg.later.click()                        # "Use without AI for now"
    assert s["no_ai"] and "Nothing goes to an AI" in dlg.privacy_label.text()
    dlg._go_next()
    assert dlg.result() == Onboarding.Accepted
    assert s["onboarding_done"] and s["no_ai"] and profiles.active.name == "Mapler"
    dlg.close()


def test_onboarding_with_the_ai_connected_leaves_the_no_ai_state(env):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb, _ = env
    s["no_ai"] = True                         # skipped once, then came back to connect
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg.restart_on_language()
    assert dlg.stack.currentWidget().findChild(type(dlg.form))       # back in on the character step
    _fill_character(dlg)
    dlg._go_next()
    dlg._on_status("claude", "ok")
    assert not dlg.later.isVisibleTo(dlg)
    dlg._go_next()
    assert not s["no_ai"] and "Claude" in dlg.privacy_label.text()


def test_onboarding_for_a_character_or_the_ai_alone(env):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb, _ = env
    s["no_ai"] = True
    dlg = Onboarding(s, profiles, kb, lambda *_: "", only_character=True)
    assert len(dlg.pages) == 1 and dlg.ai_page is None and dlg.lang_page is None
    _fill_character(dlg)
    dlg._go_next()
    assert dlg.result() == Onboarding.Accepted and profiles.active and s["no_ai"] and not s["onboarding_done"]

    dlg = Onboarding(s, profiles, kb, lambda *_: "", only_ai=True)
    assert dlg.pages == [dlg.ai_page]
    dlg._on_status("claude", "ok")
    assert not dlg.later.isVisibleTo(dlg)    # here the close button is the "not now"
    dlg._go_next()
    assert dlg.result() == Onboarding.Accepted and not s["no_ai"] and len(profiles.characters) == 1


# ---------------------------------------------------------------- settings

def test_settings_without_an_ai_asks_no_cli_and_offers_to_connect(qapp, isolated_store, kb, asked, monkeypatch):
    from maplehelper.ui import dialogs
    s = isolated_store.Settings()
    s["language"], s["provider"], s["no_ai"] = "en", "codex", True
    dlg = dialogs.SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    pump(qapp)
    assert asked == []
    assert "No AI connected" in dlg.account_label.text() and dlg.switch_btn.text() == "Connect an AI…"
    assert not dlg.usage_sec.isVisibleTo(dlg)
    dlg._on_provider("claude")               # picking an AI alone doesn't start it either
    pump(qapp)
    assert asked == []

    def connect(self):
        self.settings["no_ai"] = False
        return True
    monkeypatch.setattr(dialogs.Onboarding, "exec", connect)
    seen = []
    dlg.account_changed.connect(lambda: seen.append(s["no_ai"]))
    dlg.switch_btn.click()
    pump(qapp)
    assert seen == [False] and ("account", "claude") in asked
    assert dlg.switch_btn.text() == "Switch account" and dlg.logout_btn.isVisibleTo(dlg)     # signed in now


# ---------------------------------------------------------------- app

def test_startup_without_an_ai_starts_no_cli_and_shows_no_error(qapp, isolated_store, kb, no_spawn, asked,
                                                                 monkeypatch):
    from maplehelper import app as app_mod
    from maplehelper.ui import overlay as ov_mod
    monkeypatch.setattr(app_mod, "osapi", OSAPI)        # another test may have imported them with a thinner one
    monkeypatch.setattr(ov_mod, "osapi", OSAPI)
    monkeypatch.setattr(app_mod, "KnowledgeBase", lambda: kb)
    from maplehelper.providers import claude
    monkeypatch.setattr(claude, "find_claude", lambda: "/usr/bin/claude")   # installed: only no_ai holds it back
    toasts = []
    monkeypatch.setattr(app_mod, "notify", lambda *a, **k: toasts.append(a))
    monkeypatch.setattr(sys, "argv", ["maplehelper"])
    s = isolated_store.Settings()
    s.data.update(language="en", onboarding_done=True, no_ai=True, seen_version="999")
    s.save()
    isolated_store.Profiles().add("Mapler", "Beginner", "Beginner", 5)
    style = qapp.styleSheet()
    a = app_mod.MapleHelperApp(qapp)
    try:
        assert a.start()
        pump(qapp, 0.5)                      # the chat opens; the prewarm thread has nothing to do
        assert a.brain.no_ai
        a.summarize_session()                # the chat is open: nothing to do; then a direct summary
        assert a.brain.summarize("player: hi") is None
        a.on_account_changed()               # e.g. Settings switched provider: still nothing starts
        a.turn_on_saver()
        pump(qapp, 0.3)
        assert no_spawn == [] and asked == [] and toasts == []
    finally:
        a.shutdown()
        a.overlay.close()
        a.tray.hide()
        qapp.removeEventFilter(a.a11y)
        qapp.setStyleSheet(style)


def test_problem_report_without_an_ai_skips_the_sign_in_check(monkeypatch, tmp_path):
    from maplehelper import app as app_mod
    from maplehelper import providers, report
    monkeypatch.setattr(providers.get("claude"), "status", lambda: pytest.fail("ran the AI's CLI"))
    seen, done = {}, threading.Event()
    monkeypatch.setattr(report, "system_info", lambda *a: {"ai": a[-1]})
    monkeypatch.setattr(report, "build_report", lambda folder, info, settings: seen.update(info) or tmp_path / "r.zip")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)     # "show the file" in Explorer / Finder

    class Settings(dict):
        data = {}
    a = types.SimpleNamespace(settings=Settings(language="en", provider="claude", no_ai=True),
                              main_thread=types.SimpleNamespace(call=types.SimpleNamespace(emit=lambda fn: fn())),
                              toast=lambda *a, **k: done.set())
    app_mod.MapleHelperApp.make_report(a)
    assert done.wait(5) and seen["ai"] == "Claude: no AI"


def test_connect_ai_in_the_chat_opens_the_connect_page_without_an_ai():
    from maplehelper import app as app_mod
    calls = []
    a = types.SimpleNamespace(settings={"no_ai": True}, connect_ai=lambda: calls.append("connect"),
                              open_window=lambda *a, **k: calls.append("settings"))
    app_mod.MapleHelperApp.open_settings(a, "ai")
    assert calls == ["connect"]


def test_settings_left_open_while_the_chat_connects_never_signs_out(qapp, isolated_store, kb, asked, monkeypatch):
    """Settings showed "Connect an AI…"; the chat's Connect AI connected meanwhile. Its button still connects,
    and once the app has connected, the open window shows the account."""
    from maplehelper import app as app_mod
    from maplehelper import providers
    from maplehelper.ui import dialogs
    s = isolated_store.Settings()
    s["language"], s["no_ai"] = "en", True
    dlg = dialogs.SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    signed_out = []
    for p in providers.PROVIDERS.values():
        monkeypatch.setattr(p, "logout", lambda n=p.name: signed_out.append(n))
        monkeypatch.setattr(p, "delete_api_key", lambda n=p.name: signed_out.append(n))
    opened = []
    monkeypatch.setattr(dialogs.Onboarding, "exec", lambda self: opened.append(self.only_ai) or False)
    s["no_ai"] = False                          # connected from the chat; this window still says "Connect an AI…"
    dlg.switch_btn.click()
    pump(qapp)
    assert opened == [True] and signed_out == []

    def connect(self):
        self.settings["no_ai"] = False
        return True
    monkeypatch.setattr(app_mod, "Onboarding", type("O", (dialogs.Onboarding,), {"exec": connect}))
    s["no_ai"] = True
    dlg.sync_ai()
    refreshed = []
    a = types.SimpleNamespace(settings=s, profiles=None, kb=kb, style=lambda *_: "", _windows={"settings": dlg},
                              bring_dialogs_forward=lambda: None, on_account_changed=lambda: refreshed.append("ai"),
                              overlay=types.SimpleNamespace(refresh_profile_chip=lambda: refreshed.append("chat")))
    app_mod.MapleHelperApp.connect_ai(a)
    pump(qapp)
    assert refreshed == ["ai", "chat"]
    assert dlg.switch_btn.text() == "Switch account" and "No AI connected" not in dlg.account_label.text()
    assert signed_out == []


def test_a_provider_picked_on_a_cancelled_connect_page_does_not_stick(env):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb, _ = env
    s["no_ai"] = True
    dlg = Onboarding(s, profiles, kb, lambda *_: "", only_ai=True)
    dlg._on_provider("codex")
    assert s["provider"] == "codex"
    dlg.reject()                                # closed without connecting
    assert s["provider"] == "claude"
    dlg = Onboarding(s, profiles, kb, lambda *_: "", only_ai=True)
    dlg._on_provider("codex")
    dlg._on_status("codex", "ok")
    dlg._go_next()
    assert s["provider"] == "codex" and not s["no_ai"]
