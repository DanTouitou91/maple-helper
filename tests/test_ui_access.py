"""High contrast, screen-reader names, keyboard focus rings and the privacy page (offscreen Qt)."""
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def contrast():
    from maplehelper.ui import theme
    before = theme.MODE
    theme.set_mode("contrast")
    yield theme
    theme.set_mode(before)


def luminance(color) -> float:
    if isinstance(color, tuple):
        rgb = color
    else:
        rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    lin = [c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- high contrast

def test_high_contrast_defines_every_token_of_the_other_looks():
    from maplehelper.ui import theme
    for mode in ("dark", "light"):
        assert set(theme.PALETTES[mode]) <= set(theme.PALETTES["contrast"]), mode


def test_high_contrast_text_reads_at_7_to_1_or_more():
    from maplehelper.ui import theme
    c = theme.PALETTES["contrast"]
    for token in ("text", "muted", "faint", "accent", "danger"):
        assert ratio(c[token], c["glass"]) >= 7, token
    assert ratio("#FFFFFF", c["accent"]) >= 7          # white text on accent buttons and the player's bubble
    assert ratio(c["focus"], c["glass"]) >= 3          # the focus ring (non-text)


def test_high_contrast_is_a_choice_and_styles_the_app(qapp, contrast, isolated_store, kb):
    css = contrast.stylesheet("Rubik", 14)
    assert contrast.MODE == "contrast" and "border: 2px solid #000000" in css and "#7A3300" in css
    from maplehelper.ui.dialogs import SettingsDialog
    s = isolated_store.Settings()
    s["language"], s["no_ai"] = "en", True
    dlg = SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    assert [b.property("value") for b in dlg.appearance.group.buttons()] == ["dark", "light", "contrast"]


@pytest.mark.parametrize("mode", ["dark", "light", "contrast"])
def test_every_look_draws_a_keyboard_focus_ring(mode):
    from maplehelper.ui import theme
    before = theme.MODE
    theme.set_mode(mode)
    try:
        css = theme.stylesheet("Rubik", 14)
    finally:
        theme.set_mode(before)
    assert re.search(r'QPushButton\[keyfocus="true"\]:focus \{ outline: \dpx solid', css)
    assert all(f'QToolButton#{n}[keyfocus="true"]:focus' in css for n in theme.FOCUS_TOOL_BUTTONS)
    assert all(f'QPushButton#{n}[keyfocus="true"]:focus' in css for n in theme.FOCUS_FRAMED)


# ---------------------------------------------------------------- screen readers and focus

@pytest.fixture
def a11y(qapp):
    from maplehelper.ui import a11y
    f = a11y.install(qapp, lambda: "en")
    yield f
    qapp.removeEventFilter(f)


def test_icon_buttons_get_names_from_tooltips_or_their_icon(qapp, a11y):
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QToolButton, QWidget

    from maplehelper import bidi
    from maplehelper.ui import theme
    w = QWidget()
    lay = QHBoxLayout(w)
    tipped = QToolButton(text=theme.ICON["settings"])
    tipped.setToolTip("Settings (F9)")
    bare = QToolButton(text=theme.ICON["close"])
    rtl_glyph = QPushButton(bidi.plain(theme.ICON["delete"], True))       # rtl_buttons marks glyphs too
    named = QToolButton(text=theme.ICON["mic"])
    named.setAccessibleName("Microphone")
    words = QPushButton("Next")
    words.setToolTip("Go to the next step")
    mic = QToolButton(text=theme.SYMBOL_ICONS["mic"])        # the macOS symbols, some written as surrogate pairs
    for b in (tipped, bare, rtl_glyph, named, words, mic):
        lay.addWidget(b)
    w.show()
    qapp.processEvents()
    assert tipped.accessibleName() == "Settings (F9)"
    assert bare.accessibleName() == "Close" and rtl_glyph.accessibleName() == "Delete"
    assert named.accessibleName() == "Microphone"                         # a name set by hand stays
    assert mic.accessibleName() == "Talk"
    assert words.accessibleName() == "" and words.accessibleDescription() == "Go to the next step"
    tipped.setToolTip("Open settings")
    assert tipped.accessibleName() == "Open settings"                     # follows the tooltip
    w.close()


def test_only_keyboard_focus_is_marked_for_the_ring(qapp, a11y):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    w = QWidget()
    lay = QHBoxLayout(w)
    a, b = QPushButton("A"), QPushButton("B")
    lay.addWidget(a)
    lay.addWidget(b)
    w.show()
    w.activateWindow()
    qapp.processEvents()
    b.setFocus(Qt.MouseFocusReason)
    qapp.processEvents()
    assert b.hasFocus() and not b.property("keyfocus")
    a.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    assert a.hasFocus() and a.property("keyfocus") is True
    b.setFocus(Qt.MouseFocusReason)
    a.setFocus(Qt.MouseFocusReason)
    qapp.processEvents()
    assert not a.property("keyfocus")         # clicked this time: no ring
    w.close()


def test_settings_switches_are_named_after_their_row(qapp, isolated_store, kb):
    from maplehelper.ui.dialogs import SettingsDialog
    s = isolated_store.Settings()
    s["language"], s["no_ai"] = "en", True
    dlg = SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    assert dlg.instant.accessibleName() == "Instant answers from the database"


# ---------------------------------------------------------------- privacy

@pytest.mark.parametrize("lang", ["he", "en"])
def test_privacy_page_builds_in_both_languages(qapp, lang):
    from PySide6.QtWidgets import QLabel

    from maplehelper.i18n import I18n
    from maplehelper.ui.privacy import SECTIONS, PrivacyDialog
    t = I18n(lang)
    dlg = PrivacyDialog(lang, "")
    marks = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u2066\u2067\u2068\u2069"))
    text = "\n".join(lb.text() for lb in dlg.findChildren(QLabel)).translate(marks).casefold()
    t = (lambda tr: lambda key: tr(key).casefold())(t)          # headers show upper-case in English
    for header, rows in SECTIONS:
        assert t(header) in text
        for row, hint in rows:
            assert t(row) in text and (not hint or t(hint) in text)
    for name in ("anthropic", "openai", "github", "meowdb.com", "hugging face", t("privacy_never")):
        assert name in text
    assert dlg.windowTitle().casefold() == t("privacy")


def test_privacy_page_opens_from_settings_and_the_first_onboarding_page(qapp, isolated_store, kb, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from maplehelper.ui import privacy
    from maplehelper.ui.dialogs import Onboarding, SettingsDialog
    opened = []
    monkeypatch.setattr(privacy.PrivacyDialog, "exec", lambda self: opened.append(self.t.lang))
    s = isolated_store.Settings()
    s["language"], s["no_ai"] = "en", True
    dlg = SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    next(b for b in dlg.findChildren(QPushButton) if b.text() == "Privacy").click()
    ob = Onboarding(s, isolated_store.Profiles(), kb, lambda *_: "")
    next(b for b in ob.lang_page.findChildren(QPushButton) if b.text() == "Privacy").click()
    assert opened == ["en", "en"]


@pytest.mark.parametrize("lang", ["he", "en"])
def test_privacy_page_tells_the_whole_story(lang):
    """The page names every outbound flow and local file the code has (see the SECTIONS comment)."""
    from maplehelper.i18n import I18n
    from maplehelper.ui.privacy import SECTIONS
    t = I18n(lang)
    text = " ".join(t(k) for _, rows in SECTIONS for r in rows for k in r if k)
    for needle in ("30" if lang == "en" else "חצי שעה", "Claude Code / Codex", "3", "feedback.json", "costs.json"):
        assert needle in text
    assert t("session_summaries") in t("privacy_ai_summary_hint")     # the switch the hint points at exists
    assert t.p("ob_privacy", "claude").count("Claude") == 1 and "OpenAI" in t.p("ob_privacy", "codex")
