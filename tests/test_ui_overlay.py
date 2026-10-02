"""The chat window's behaviour (offscreen Qt, a stand-in AI, no game)."""
import os
import sys
import threading
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


def _no_game_osapi():
    """winapi needs Windows (ctypes.windll): elsewhere the chat runs against a stand-in OS layer."""
    try:
        import maplehelper.osapi  # noqa: F401
    except (AttributeError, ImportError):
        stub = types.ModuleType("maplehelper.osapi")
        stub.IS_MAC = False
        stub.SCREEN_COORDS_ARE_PHYSICAL = False
        for name in ("find_game_window", "capture_game", "window_rect", "float_over_fullscreen", "activate_self",
                     "focus_window"):
            setattr(stub, name, lambda *a, **k: None)
        sys.modules["maplehelper.osapi"] = stub
        import maplehelper
        maplehelper.osapi = stub


_no_game_osapi()


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class FakeBrain:
    """Answers after streaming a few tokens; cancel() ends a running answer at once."""

    def __init__(self, hold=False):
        self.cancelled = threading.Event()
        self.hold = hold

    def ask(self, question, character, history, shot, on_delta=None, focus=None, on_status=None):
        from maplehelper.brain import Answer
        for part in ("Hel", "Hello", "Hello there", "Hello there"):
            if on_delta:
                on_delta(part)
        if self.hold:
            self.cancelled.wait(5)
            return Answer(error="cancelled")
        return Answer(text="Hello there")

    def cancel(self):
        self.cancelled.set()

    def begin(self):
        pass


@pytest.fixture
def overlay(qapp, isolated_store, kb):
    from maplehelper.ui.overlay import Overlay
    s = isolated_store.Settings()
    s["language"] = "en"
    s["instant_answers"] = False
    ov = Overlay(s, isolated_store.Profiles(), kb, FakeBrain())
    yield ov
    ov.close()


def wait(qapp, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    return cond()


def test_partial_meta_marker_is_hidden():
    from maplehelper.ui.overlay import _visible
    assert _visible("Kill Snails @@ME") == "Kill Snails"
    assert _visible("Kill Snails\n@") == "Kill Snails"
    assert _visible("mail me a@b") == "mail me a@b"
    assert _visible("Done.") == "Done."


def test_bubble_renders_a_text_once(qapp):
    from maplehelper.ui.widgets import Bubble
    b = Bubble("", "assistant", False)
    shown = []
    b.label.setText = shown.append
    for _ in range(3):
        b.set_text("Go to Henesys", explain=False)
    b.set_text("Go to Henesys")                # done: rendered once more, now with the "?" beside terms
    assert len(shown) == 2


def test_streaming_renders_the_newest_text_and_the_answer_once_done(qapp, overlay):
    from maplehelper.ui.widgets import Bubble
    renders = []
    real = Bubble.set_text

    def spy(self, text, explain=True):
        renders.append((text, explain))
        real(self, text, explain)
    Bubble.set_text = spy
    try:
        assert overlay.ask("hi")
        assert wait(qapp, lambda: not overlay.busy)
    finally:
        Bubble.set_text = real
    streamed = [r for r in renders if not r[1]]
    assert len(streamed) <= 1                           # four tokens in a burst: one render at most
    assert renders[-1] == ("Hello there", True)
    assert overlay._pending_bubble._shown == ("Hello there", True)
    from maplehelper.ui.overlay import _alive
    assert wait(qapp, lambda: not _alive(overlay._thread) and not _alive(overlay._worker))    # no thread per question left


def test_stop_ends_a_running_answer(qapp, overlay):
    overlay.brain = FakeBrain(hold=True)
    assert overlay.ask("tell me everything")
    assert overlay.send_btn.isEnabled()                  # mid-answer, send is the stop button
    overlay.stop_answer()
    assert overlay.brain.cancelled.is_set()
    assert wait(qapp, lambda: not overlay.busy)
    assert overlay._pending_bubble._shown[0] == overlay.t("answer_stopped")
    assert not overlay._stopping
    assert overlay.ask("next question")                  # the chat is free again
    assert wait(qapp, lambda: not overlay.busy)


def test_the_feed_keeps_the_newest_rows(qapp, overlay):
    overlay.busy = True
    overlay._pending_bubble = overlay.add_bubble("working…", "assistant")
    for i in range(overlay.MAX_ROWS + 30):
        overlay.add_system(f"line {i}")
    assert overlay.feed_lay.count() - 1 == overlay.MAX_ROWS
    assert overlay.feed_lay.itemAt(0).widget().isAncestorOf(overlay._pending_bubble)   # the answer being written stays
    overlay.busy = False
    overlay.add_system("one more")
    assert overlay.feed_lay.count() - 1 == overlay.MAX_ROWS
    assert overlay._pending_bubble is None


def test_a_read_while_answering_reports_back(qapp, overlay):
    got = []
    overlay.sync_finished.connect(got.append)
    overlay.busy = True
    overlay.sync_profile()
    assert got == [False]                    # an EXP meter waiting for it isn't stuck on "reading…"


def test_a_failed_screenshot_brings_the_chat_back(qapp, overlay, monkeypatch):
    from maplehelper import osapi
    monkeypatch.setattr(osapi, "find_game_window", lambda: 42)

    def broken(hwnd):
        raise OSError("capture failed")
    overlay.shot_provider = broken
    overlay.recapture()
    assert overlay.windowOpacity() == 0.0
    assert wait(qapp, lambda: overlay.windowOpacity() == 1.0)
    assert overlay.shot is None


def test_term_popups_follow_a_language_switch(qapp, overlay, monkeypatch):
    from maplehelper.ui import terms
    from maplehelper.ui.widgets import Bubble
    seen = []
    monkeypatch.setattr(terms, "_hovered", lambda link, lang: seen.append(lang))
    b = Bubble("Use Power Strike", "assistant", False)
    overlay.settings["language"] = "he"
    overlay.apply_language()
    b.label.linkHovered.emit("g:EXP")
    overlay.settings["language"] = "en"
    overlay.apply_language()
    b.label.linkHovered.emit("g:EXP")
    assert seen == ["he", "en"]


def test_cards_restyle_only_when_their_selection_changes(qapp, kb):
    from maplehelper.ui.widgets import SELECTION, EntityCard
    card = EntityCard(kb, "monster/100100", "en")
    calls = []
    card.style = lambda: types.SimpleNamespace(unpolish=calls.append, polish=calls.append)
    SELECTION.changed.emit(["monster/100101"])
    assert calls == []
    SELECTION.changed.emit(["monster/100100"])
    SELECTION.changed.emit(["monster/100100", "monster/100101"])
    assert len(calls) == 2                  # one unpolish + one polish, for the one real change


def test_the_stylesheet_is_built_once_and_not_applied_twice(qapp):
    from PySide6.QtWidgets import QWidget
    from maplehelper.ui import theme
    css = theme.stylesheet("Rubik", 14)
    assert theme.stylesheet("Rubik", 14) is css
    old = qapp.styleSheet()
    qapp.setStyleSheet(css)
    try:
        w = QWidget()
        theme.apply(w, css)
        assert w.styleSheet() == ""         # the app already carries it
        theme.apply(w, "QWidget { color: red; }")
        assert w.styleSheet() == "QWidget { color: red; }"
    finally:
        qapp.setStyleSheet(old)


def test_thumbnails_are_scaled_once(qapp, kb):
    from maplehelper.ui import theme
    path = kb.picture("monster/100100")
    a = theme.thumb(path, 32)
    assert not a.isNull() and max(a.width(), a.height()) == 32
    assert theme.thumb(path, 32).cacheKey() == a.cacheKey()
    assert theme.thumb(None, 32).isNull()


def test_a_quick_double_toggle_keeps_the_window_size(qapp, overlay):
    from PySide6.QtCore import QRect
    overlay.setGeometry(QRect(100, 100, 640, 700))
    overlay.show()
    overlay._materialize(True)
    wait(qapp, lambda: False, 0.05)                  # cut the grow short
    overlay._materialize(False)
    overlay._materialize(True)
    assert overlay.geometry().width() < 640          # growing again...
    overlay.save_geometry()
    assert overlay.settings["window"]["w"] == 640     # ...and what is saved is the real size
    assert wait(qapp, lambda: overlay._target_geometry is None)
    assert overlay.geometry() == QRect(100, 100, 640, 700)


def test_f9_twice_quickly_opens_the_chat_again(qapp, overlay):
    """The second F9 lands while the chat fades out (still visible): it opens it again, as a toggle should."""
    from maplehelper import app as app_mod
    a = types.SimpleNamespace(overlay=overlay, capture=lambda hwnd: None)
    overlay.toggle(a.capture)
    assert wait(qapp, lambda: overlay.windowOpacity() >= overlay.full_opacity() - 0.01)
    app_mod.MapleHelperApp.on_hotkey(a, app_mod.HOTKEY_TOGGLE)
    assert overlay.isVisible() and not overlay.is_open()      # fading out
    app_mod.MapleHelperApp.on_hotkey(a, app_mod.HOTKEY_TOGGLE)
    wait(qapp, lambda: False, 0.5)
    assert overlay.isVisible() and overlay.is_open() and overlay.windowOpacity() > 0.5
    app_mod.MapleHelperApp.on_hotkey(a, app_mod.HOTKEY_TOGGLE)
    assert wait(qapp, lambda: not overlay.isVisible())        # one F9 still closes it
