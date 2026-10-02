"""Screen readers and keyboard players, for every window at once (one app-wide event filter).

Icon-only buttons draw a glyph from the icon font, which a screen reader would read as a private-use
character: they get a name from their tooltip, or from the icon's own name. A button focused with Tab
is marked keyfocus=true, so the stylesheet draws a focus ring for the keyboard and none for a click.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton

from ..i18n import STRINGS, I18n
from . import theme

KEYBOARD = (Qt.TabFocusReason, Qt.BacktabFocusReason)
RETURNING = (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason)     # focus comes back: the mark stays as it was


def _icon_key(text: str) -> str | None:
    """The theme.ICON name of a glyph-only label ("" when it's no known icon but still no words)."""
    text = text.strip().strip("\u200e\u200f\u2066\u2067\u2068\u2069")     # bidi marks (rtl_buttons, bidi.plain)
    for icons in (theme.ICON, theme.SYMBOL_ICONS):
        for key, glyph in icons.items():
            # a few symbols are written as UTF-16 surrogate pairs ("\ud83c\udf99"): compare as Qt shows them
            if text == glyph.encode("utf-16", "surrogatepass").decode("utf-16"):
                return key
    return "" if not text or all("\ue000" <= ch <= "\uf8ff" for ch in text) else None


def name_button(b: QAbstractButton, t: I18n) -> None:
    """Fill in a missing accessible name (icon-only buttons) and description (from the tooltip)."""
    tip = b.toolTip().strip()
    key = _icon_key(b.text())
    if key is not None and (not b.accessibleName() or b.property("a11y_auto")):
        name = tip or (t(f"a11y_{key}") if f"a11y_{key}" in STRINGS else "")
        if name and name != b.accessibleName():
            b.setAccessibleName(name)
            b.setProperty("a11y_auto", True)       # ours: may follow a later tooltip change
    if tip and not b.accessibleDescription() and tip != b.accessibleName():
        b.setAccessibleDescription(tip)


class Accessibility(QObject):
    """Installed on the QApplication: sees every button as it appears, and every focus change."""

    def __init__(self, language):
        super().__init__()
        self.language = language         # callable: the UI language now

    def eventFilter(self, obj, e):
        kind = e.type()
        if kind in (QEvent.Show, QEvent.ToolTipChange) and isinstance(obj, QAbstractButton):
            name_button(obj, I18n(self.language() or "he"))
        elif kind == QEvent.FocusIn and isinstance(obj, QAbstractButton) and e.reason() not in RETURNING:
            keyboard = e.reason() in KEYBOARD
            if bool(obj.property("keyfocus")) != keyboard:
                obj.setProperty("keyfocus", keyboard)
                obj.style().unpolish(obj)          # property selectors are matched when polished
                obj.style().polish(obj)
        return False


def install(qapp, language) -> Accessibility:
    f = Accessibility(language)
    f.setParent(qapp)             # lives as long as the app, whoever keeps the returned object
    qapp.installEventFilter(f)
    return f
