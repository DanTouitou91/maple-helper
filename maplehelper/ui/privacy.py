"""Privacy in plain words: what leaves the computer, where to, and what never does."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import bidi
from ..i18n import I18n
from . import theme
from .controls import Section
from .glass import GlassDialog

# (section header, [(row, hint or None)]): each line matches what the code does (brain.py, updater.py,
# market.py, voice.py, providers/base.py, report.py)
SECTIONS = [
    ("privacy_sec_ai", [("privacy_ai_question", None), ("privacy_ai_shot", None), ("privacy_ai_profile", None),
                        ("privacy_ai_chat", None), ("privacy_ai_where", "privacy_ai_where_hint")]),
    ("privacy_sec_net", [("GitHub", "privacy_net_github"), ("meowdb.com", "privacy_net_meowdb"),
                         ("Hugging Face", "privacy_net_hf")]),
    ("privacy_sec_local", [("privacy_local_chats", None), ("privacy_local_voice", None),
                           ("privacy_local_keys", None), ("privacy_local_report", None)]),
]


class PrivacyDialog(GlassDialog):
    def __init__(self, lang: str, stylesheet: str):
        self.t = t = I18n(lang or "he")
        super().__init__(t("privacy"), t.rtl)
        theme.apply(self, stylesheet)
        self.resize(480, 640)
        rtl = t.rtl
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(16)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        intro = QLabel(bidi.plain(t("privacy_intro"), rtl), objectName="PageBody")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        for header, rows in SECTIONS:
            sec = Section(t(header), rtl)
            for row, hint in rows:
                sec.add_row(t(row), hint=t(hint) if hint else "")      # a site name has no string: shown as is
            lay.addWidget(sec)
        never = QLabel(bidi.plain(t("privacy_never"), rtl), objectName="RowLabel")
        never.setWordWrap(True)
        never.setStyleSheet("font-weight: 600;")
        lay.addWidget(never)
        lay.addStretch(1)
