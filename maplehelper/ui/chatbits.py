"""Small chat extras: tappable question chips that wrap into rows, and the 👍/👎 under an answer."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QPushButton, QToolButton, QVBoxLayout, QWidget

from .. import bidi


class Flow(QLayout):
    """Its widgets in as many rows as the width needs (from the right in a right-to-left UI)."""

    def __init__(self, gap: int = 6):
        super().__init__()
        self._items = []
        self._gap = gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w: int) -> int:
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, r: QRect):
        super().setGeometry(r)
        self._place(r, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _place(self, r: QRect, move: bool) -> int:
        w = self.parentWidget()
        rtl = w is not None and w.layoutDirection() == Qt.RightToLeft
        x, y, row_h = 0, 0, 0
        for it in self._items:
            hint = it.sizeHint()
            if x and x + hint.width() > r.width():
                x, y, row_h = 0, y + row_h + self._gap, 0
            if move:
                left = r.x() + (r.width() - x - hint.width() if rtl else x)
                it.setGeometry(QRect(QPoint(left, r.y() + y), hint))
            x += hint.width() + self._gap
            row_h = max(row_h, hint.height())
        return y + row_h


class Chips(QWidget):
    """Questions to tap (an empty chat's starters, an answer's follow-ups), under an optional title."""

    def __init__(self, title: str = ""):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(2, 0, 2, 0)
        col.setSpacing(6)
        self.title = QLabel(objectName="TileGridTitle")
        self.title.setVisible(bool(title))
        self.title.setText(title)
        col.addWidget(self.title)
        box = QWidget()
        self.flow = Flow()
        box.setLayout(self.flow)
        col.addWidget(box)

    def set_title(self, title: str, rtl: bool):
        self.title.setText(bidi.plain(title, rtl))
        self.title.setVisible(bool(title))

    def add(self, text: str, on_click, kind: str = "SubChip", rtl: bool = False) -> QPushButton:
        b = QPushButton(bidi.plain(text, rtl).replace("&", "&&"), objectName=kind)     # "&" isn't a shortcut
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: on_click())
        self.flow.addWidget(b)
        return b

    def clear(self):
        while self.flow.count():
            w = self.flow.takeAt(0).widget()
            w.hide()
            w.deleteLater()

    def count(self) -> int:
        return self.flow.count()


class Rating(QWidget):
    """👍 / 👎 on an answer; once rated, only the chosen one stays."""

    rated = Signal(str)          # "up" | "down"

    def __init__(self, t):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.buttons = {}
        for rating, glyph in (("up", "👍"), ("down", "👎")):
            b = self.buttons[rating] = QToolButton(objectName="Icon", text=glyph)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(t(f"rate_{rating}"))
            b.clicked.connect(lambda _=False, r=rating: self.rate(r))
            lay.addWidget(b)

    def rate(self, rating: str):
        for r, b in self.buttons.items():
            b.setVisible(r == rating)
            b.setEnabled(False)
        self.rated.emit(rating)


def footer(bubble) -> QHBoxLayout:
    """The row of small controls under a finished answer: the one Bubble.add_pin just made."""
    lay = bubble.layout()
    return lay.itemAt(lay.count() - 1).layout()
