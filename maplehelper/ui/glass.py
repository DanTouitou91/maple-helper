"""The glass material every window paints, and the frameless glass dialog."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from . import theme

SHADOW = 12


def glass_path(widget, radius: float = None) -> QPainterPath:
    r = theme.RADIUS if radius is None else radius
    path = QPainterPath()
    path.addRoundedRect(QRectF(widget.rect()).adjusted(SHADOW + 0.5, SHADOW + 0.5, -SHADOW - 0.5, -SHADOW - 0.5), r, r)
    return path


def paint_glass(widget, radius: float = None) -> None:
    """The one material every window uses: soft shadow, neutral tint, sheen, rim."""
    c = theme.P()
    r = theme.RADIUS if radius is None else radius
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for i in range(SHADOW, 0, -2):
        sh = QPainterPath()
        sh.addRoundedRect(QRectF(widget.rect()).adjusted(SHADOW - i, SHADOW - i + 3, -(SHADOW - i), -(SHADOW - i) + 3),
                          r + i, r + i)
        p.fillPath(sh, QColor(0, 0, 0, int(26 * (1 - i / SHADOW)) + 2))
    path = glass_path(widget, r)
    p.save()
    p.setClipPath(path)
    tint = QColor(*c["glass"])
    tint.setAlphaF(c["solid_alpha"])
    p.fillPath(path, tint)
    sheen = QLinearGradient(0, SHADOW, 0, SHADOW + min(170, widget.height()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, c["sheen"]))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    p.restore()
    rim = QLinearGradient(0, SHADOW, 0, widget.height() - SHADOW)
    rim.setColorAt(0.0, QColor(255, 255, 255, c["rim_top"]))
    rim.setColorAt(0.4, QColor(255, 255, 255, c["rim"]))
    rim.setColorAt(1.0, QColor(255, 255, 255, c["rim"] // 2))
    p.setPen(QPen(rim, 1))
    p.drawPath(path)
    if c.get("edge"):              # high contrast: a solid edge, the rim is invisible on white
        p.setPen(QPen(QColor(c["edge"]), 2))
        p.drawPath(path)
    p.end()


class _DragBar(QWidget):
    def __init__(self, win):
        super().__init__()
        self._win, self._grab = win, None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._grab = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._grab is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, e):
        self._grab = None


class GlassDialog(QDialog):
    """Frameless glass window with the app's own title bar (title + close). Put content in self.content."""

    def __init__(self, title: str, rtl: bool, show_in_captures: bool = False, closable: bool = True,
                 strength: float = 0.6):
        # on top like the chat and Settings, or a confirmation opened from Settings hides behind it
        super().__init__(None, Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self._show_in_captures = show_in_captures
        self._strength = strength
        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW + 18, SHADOW + 10, SHADOW + 18, SHADOW + 16)
        root.setSpacing(8)
        bar = _DragBar(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 4)
        self.title_label = QLabel(title, objectName="Title")
        bl.addWidget(self.title_label)
        bl.addStretch(1)
        self.close_btn = QToolButton(objectName="IconClose", text=theme.ICON["close"])
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setVisible(closable)
        bl.addWidget(self.close_btn)
        root.addWidget(bar)
        self.content = QWidget(objectName="Feed")
        root.addWidget(self.content, 1)

    def paintEvent(self, e):
        paint_glass(self)
