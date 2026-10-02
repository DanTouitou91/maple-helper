"""The wishlist window: each wished item, who drops it (lowest level first) and where they live, and its
Free Market price, with a heads-up when it drops."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import bidi, market, wishlist
from ..i18n import I18n
from ..kb import KnowledgeBase
from . import theme
from .controls import rtl_buttons
from .glass import GlassDialog
from .widgets import EntityCard, drop_badge

SHOWN_DROPPERS = 5
_CHECKED: set[str] = set()       # items whose price this app session already looked up (once, unless asked)


class WishlistDialog(GlassDialog):
    price_ready = Signal(object)          # (item key, Market or None) from the background lookup; None = all done
    price_dropped = Signal(str, str)      # a toast: (title, message)

    def __init__(self, keys: list[str], kb: KnowledgeBase, lang: str, stylesheet: str, settings=None):
        self.t = t = I18n(lang or "he")
        super().__init__(t("wishlist"), t.rtl)
        self.kb, self.settings = kb, settings
        theme.apply(self, stylesheet)
        self.resize(500, 640)
        rtl = t.rtl
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        self.lay = lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.keys = keys = [k for k in keys if kb.get(k)]
        if not keys:
            empty = QLabel(bidi.plain(t("wishlist_empty"), rtl), objectName="DialogBody")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute
        self.prices: dict[str, QLabel] = {}
        for k in keys:
            lay.addWidget(EntityCard(kb, k, t.lang))
            droppers = kb.droppers.get(k, [])
            if droppers:
                lines = [(t("wish_dropped_by"), None)]
                for m in droppers[:SHOWN_DROPPERS]:
                    e = kb.get(m) or {}
                    lvl = (e.get("props") or {}).get("Level")
                    maps = kb._top_maps(m, n=1)
                    lines.append((f"• {e.get('name', m)}" + (f" (Lv. {lvl})" if lvl else "")
                                  + (f" · {maps[0]}" if maps else ""), kb.badge_source(m, k)))
                if len(droppers) > SHOWN_DROPPERS:
                    lines.append((t("pn_more", n=len(droppers) - SHOWN_DROPPERS), None))
            else:
                lines = [(t("wish_no_droppers"), None)]
            for ln, source in lines:
                lb = QLabel(bidi.plain(ln, rtl), objectName="CardStat")
                lb.setWordWrap(True)
                lb.setAlignment(align)
                lb.setContentsMargins(12, 0, 12, 0)
                badge = drop_badge(source)
                if badge is None:
                    lay.addWidget(lb)
                    continue
                line = QHBoxLayout()
                line.setContentsMargins(0, 0, 12, 0)
                line.addWidget(lb, 1)
                line.addWidget(badge, 0, Qt.AlignVCenter)
                lay.addLayout(line)
            if settings is not None:
                price = self.prices[k] = QLabel(objectName="CardSub")
                price.hide()
                line = QHBoxLayout()
                line.setContentsMargins(12, 2, 12, 0)
                line.addWidget(price)
                line.addStretch(1)
                lay.addLayout(line)
                self._show_price(k, (settings["wish_prices"] or {}).get(k) or {})
            lay.addSpacing(10)
        lay.addStretch(1)

        self.status = QLabel(objectName="RowHint")
        self.status.setAlignment(Qt.AlignHCenter)
        self.status.hide()
        outer.addWidget(self.status)
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.addStretch(1)
        if settings is not None and keys:
            check = QPushButton(t("wish_check_prices"), objectName="Secondary")
            check.setCursor(Qt.PointingHandCursor)
            check.clicked.connect(lambda: self.check_prices(force=True))
            row.addWidget(check)
        ok = QPushButton(t("close"), objectName="Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.setMinimumWidth(160)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        row.addStretch(1)
        outer.addLayout(row)
        rtl_buttons(self, rtl)
        self.price_ready.connect(self._on_price)
        if settings is not None:
            self.check_prices()

    # Free Market prices ----------------------------------------------------

    def check_prices(self, force: bool = False):
        """Look the prices up off the GUI thread: each item once per app session, or all of them on request
        (the market module's own cache still applies). Offline is silent: the last known prices stay."""
        todo = [(k, self.kb.get(k)["name"]) for k in self.keys if force or k not in _CHECKED]
        if not todo:
            return
        _CHECKED.update(k for k, _ in todo)
        self.status.setText(bidi.plain(self.t("wish_checking"), self.t.rtl))
        self.status.show()

        def run():
            try:
                for k, name in todo:
                    self.price_ready.emit((k, market.free_market(name)))
                self.price_ready.emit(None)
            except RuntimeError:
                pass                     # the window closed meanwhile
        threading.Thread(target=run, daemon=True).start()

    def _on_price(self, result):
        if result is None:
            self.status.hide()
            return
        key, m = result
        if m is None or not m.median:
            return
        rec, news = wishlist.price_seen(self.settings, key, m.median)
        self._show_price(key, rec)
        if news:
            t = self.t
            self.price_dropped.emit(t("wish_price_toast"), t("wish_price_toast_body", name=self.kb.get(key)["name"],
                                                             n=f"{rec['median']:,}", was=f"{rec['was']:,}"))

    def _show_price(self, key: str, rec: dict):
        lb = self.prices.get(key)
        if lb is None or not rec.get("median"):
            return
        t = self.t
        down = bool(rec.get("was"))
        text = (t("wish_price_drop", n=f"{rec['median']:,}", was=f"{rec['was']:,}") if down
                else t("wish_price", n=f"{rec['median']:,}"))
        lb.setText(bidi.plain(text, t.rtl))
        lb.setObjectName("TagGood" if down else "CardSub")      # a drop stands out
        lb.style().unpolish(lb)
        lb.style().polish(lb)
        lb.show()
