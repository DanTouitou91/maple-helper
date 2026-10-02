"""The in-game chat window: a liquid-glass panel over the game, draggable across monitors, F9 only to close."""
from __future__ import annotations

import time

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QObject, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QRect, QRectF, Qt, QThread, QTimer, Signal)
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPainterPath, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QScrollArea, QSizeGrip, QToolButton, QVBoxLayout, QWidget)

from .. import __version__, bidi, osapi, quick
from ..brain import META, Answer, Brain
from ..i18n import STRINGS, I18n
from ..kb import KnowledgeBase
from ..session import SessionStats, lines as session_lines, questions as session_questions
from ..store import ASSETS, History, Profiles, Settings
from . import theme
from .glass import paint_glass
from .minibubble import MiniBubble
from .widgets import (SELECTION, WISHLIST, Bubble, BubbleRow, DropGroupCard, EntityCard, NoticeCard, ProfileCard,
                      SessionCard, SystemLine, TileGrid, character_image)
from .chatbits import Chips, Rating, footer



class AskWorker(QObject):
    delta = Signal(str)
    status = Signal(str)          # what the AI looks up before it writes ("search", "read:<kb key>")
    done = Signal(object)

    def __init__(self, brain: Brain, question: str, character, history, shot: bytes | None, focus=None):
        super().__init__()
        self.brain, self.question, self.character, self.history, self.shot = brain, question, character, history, shot
        self.focus = focus

    def run(self):
        # whatever happens, the chat gets an answer back (never stuck on "thinking")
        try:
            ans = self.brain.ask(self.question, self.character, self.history, self.shot, on_delta=self.delta.emit,
                                 focus=self.focus, on_status=self.status.emit)
        except Exception as e:  # noqa: BLE001
            ans = Answer(error=f"internal: {e}")
        self.done.emit(ans)


class TitleBar(QWidget):
    """Drag handle: follows the pointer 1:1 from where it was grabbed."""

    def __init__(self, window: QWidget):
        super().__init__()
        self._win = window
        self._grab: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._grab = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._grab is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, e):
        if self._grab is not None:
            self._grab = None
            self._win.save_geometry()


class Capsule(QFrame):
    """Input capsule; highlights its border while the field has focus."""

    def set_focus_look(self, on: bool):
        self.setProperty("focus", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class FocusLineEdit(QLineEdit):
    focus_changed = Signal(bool)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)


def _visible(text: str) -> str:
    """A streaming answer can end in the first characters of the hidden @@META@@ marker: don't flash them."""
    for n in range(len(META) - 1, 0, -1):
        if text.endswith(META[:n]):
            return text[:-n].rstrip()
    return text


# an answer's error code -> (its text, the one-tap fix: (button text, what it does) or None).
# The text says what to do; the button does it.
ERRORS = {
    "offline": ("err_offline", ("retry", "retry")),
    "timeout": ("err_timeout", ("retry", "retry")),
    "no_result": ("err_no_result", ("retry", "retry")),
    "api_error": ("err_api_error", ("retry", "retry")),
    "not_logged_in": ("err_not_logged_in", ("sign_in", "settings")),
    "not_installed": ("err_not_installed", ("fix_install", "settings")),
    "launch_failed": ("err_launch_failed", ("fix_settings", "settings")),
    "no_ai": ("err_no_ai", ("fix_connect_ai", "settings")),
    "usage_limit": ("err_usage_limit", ("saver_turn_on", "saver")),
}


def error_view(code: str, saver_on: bool = False) -> tuple[str, tuple | None]:
    """The text key and the fix for an error code ("launch_failed: <detail>" counts as launch_failed)."""
    text, fix = ERRORS.get((code or "").split(":")[0], ("err_generic", ("retry", "retry")))
    return text, None if fix[1] == "saver" and saver_on else fix


def _alive(w) -> bool:
    """False once Qt deleted the widget (e.g. the chat was cleared)."""
    try:
        from shiboken6 import isValid
        return isValid(w)
    except Exception:
        return False


class Overlay(QWidget):
    history_requested = Signal()
    guides_requested = Signal()
    guide_requested = Signal(str)
    saver_requested = Signal()
    wishlist_requested = Signal()
    closed = Signal()
    update_requested = Signal()
    settings_requested = Signal()
    profile_requested = Signal()
    add_character_requested = Signal()
    mic_clicked = Signal()
    limits_read = Signal(object)
    profile_changed = Signal()        # level / EXP / stats changed (a screenshot read or the chat)
    sync_finished = Signal(bool)      # a screenshot read ended (True = it read the game)
    tools_requested = Signal()
    edit_character_requested = Signal(str)
    delete_character_requested = Signal(str)      # plan usage read in the background after an answer (ChatGPT)
    tools_page_requested = Signal(str)            # "Open in play tools" under an answer: that page
    settings_section_requested = Signal(str)      # an error's fix: Settings at that section ("ai")

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, brain: Brain):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        from . import terms
        terms.setup()
        self.setObjectName("Overlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)   # macOS hides tool windows of inactive apps
        self.setWindowTitle("Maple Helper")
        self.settings, self.profiles, self.kb, self.brain = settings, profiles, kb, brain
        self.t = I18n(settings["language"] or "he")
        self.game_hwnd: int | None = None
        self.shot: bytes | None = None          # screenshot for the next question
        self.shot_used = False
        self.busy = False
        self._thread: QThread | None = None
        self._pending_bubble: Bubble | None = None
        self._session_started: float | None = None
        self.stats: SessionStats | None = None
        self._anim: QParallelAnimationGroup | None = None
        self._target_geometry: QRect | None = None     # where a growing window is going
        self._save_timer = QTimer(self, singleShot=True, interval=300, timeout=self.save_geometry)
        # a streaming answer renders at most every 60 ms, always its newest text
        self._delta_text = ""
        self._delta_timer = QTimer(self, singleShot=True, interval=60, timeout=self._render_delta)
        self._stopping = False                         # the player stopped the answer; waiting for it to end
        self.bubble = MiniBubble()
        self.bubble.clicked.connect(self.restore_from_bubble)
        self.bubble.moved.connect(lambda pt: self.settings.__setitem__("bubble_pos", {"x": pt.x(), "y": pt.y()}))
        self.shot_provider = None
        self._build()
        WISHLIST.bind(settings, profiles)
        self.apply_language()
        self.restore_geometry()

    # ------------------------------------------------------------------ material

    SHADOW = 12   # room around the panel for its soft shadow

    def apply_capture_mode(self):
        """Opaque window, visible in screenshots and recordings like any app."""
        self.update()

    def _panel_path(self) -> QPainterPath:
        m = self.SHADOW
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(m + 0.5, m + 0.5, -m - 0.5, -m - 0.5),
                            theme.RADIUS, theme.RADIUS)
        return path

    def paintEvent(self, e):
        """Liquid glass: the blurred game behind, a neutral tint, a light-catching sheen and rim."""
        paint_glass(self)

    # ------------------------------------------------------------------ layout

    def _icon_button(self, glyph: str, tip: str = "") -> QToolButton:
        b = QToolButton(objectName="Icon", text=glyph)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        return b

    def _build(self):
        lay = QVBoxLayout(self)
        m = self.SHADOW
        lay.setContentsMargins(m + 14, m + 10, m + 14, m + 12)
        lay.setSpacing(10)

        # header: app mark · name · version · settings
        self.title_bar = TitleBar(self)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(2, 2, 0, 0)
        tb.setSpacing(8)
        logo = QLabel()
        icon = ASSETS / "brand" / "icon-64.png"
        if icon.exists():
            logo.setPixmap(QPixmap(str(icon)).scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        tb.addWidget(logo)
        self.title = QLabel("Maple Helper", objectName="Title")
        tb.addWidget(self.title)
        self.version_label = QLabel(f"v{__version__}", objectName="Version")
        self.version_label.setLayoutDirection(Qt.LeftToRight)
        tb.addWidget(self.version_label)
        self.saver_badge = QLabel(objectName="SaverBadge")
        self.saver_badge.hide()
        tb.addWidget(self.saver_badge)
        tb.addStretch(1)
        self.history_btn = self._icon_button(theme.ICON["search"])
        self.history_btn.clicked.connect(self.history_requested.emit)
        tb.addWidget(self.history_btn)
        self.tools_btn = self._icon_button(theme.ICON["tools"])
        self.tools_btn.setToolTip(self.t("tools"))
        self.tools_btn.clicked.connect(self.tools_requested.emit)
        tb.addWidget(self.tools_btn)
        self.guides_btn = self._icon_button(theme.ICON["book"])
        self.guides_btn.clicked.connect(self.guides_requested.emit)
        tb.addWidget(self.guides_btn)
        self.wish_btn = self._icon_button(theme.ICON["star"])
        self.wish_btn.clicked.connect(self.wishlist_requested.emit)
        tb.addWidget(self.wish_btn)
        self.settings_btn = self._icon_button(theme.ICON["settings"])
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        tb.addWidget(self.settings_btn)
        # window controls sit at the header's edge (left in Hebrew, right in English)
        self.min_btn = self._icon_button(theme.ICON["minimize"])
        self.min_btn.clicked.connect(self.minimize)
        tb.addWidget(self.min_btn)
        self.close_btn = self._icon_button(theme.ICON["close"])
        self.close_btn.setObjectName("IconClose")
        self.close_btn.clicked.connect(self.close_overlay)
        tb.addWidget(self.close_btn)
        lay.addWidget(self.title_bar)

        # a new version is downloaded: one tap installs it and reopens the app
        self.update_bar = QFrame(objectName="InfoNote")
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(12, 6, 8, 6)
        ub.setSpacing(10)
        ub.addWidget(QLabel(theme.ICON["refresh"], objectName="InfoIcon"), 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.update_label = QLabel(objectName="InfoText")
        self.update_label.setWordWrap(True)
        col.addWidget(self.update_label)
        from PySide6.QtWidgets import QProgressBar
        self.update_progress = QProgressBar(objectName="ExpBar")
        self.update_progress.setRange(0, 1000)
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedHeight(6)
        self.update_progress.hide()
        col.addWidget(self.update_progress)
        ub.addLayout(col, 1)
        self.update_btn = QPushButton(objectName="Primary")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self.update_requested.emit)
        ub.addWidget(self.update_btn)
        self.update_bar.hide()
        lay.addWidget(self.update_bar)

        # the character, pinned at the top of the conversation
        self.profile_card = ProfileCard()
        self.profile_card.refresh_requested.connect(self.sync_profile)
        self.profile_card.clicked.connect(self.character_menu)
        self.profile_card.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.profile_card)
        from .plancard import TipStrip
        self.tip_strip = TipStrip()
        self.tip_strip.asked.connect(self.ask)
        self.tip_strip.dismissed.connect(self._dismiss_tip)
        lay.addWidget(self.tip_strip)
        from .pinsview import PinsBar
        self.pins_bar = PinsBar()
        self.pins_bar.unpin.connect(self._unpin)
        lay.addWidget(self.pins_bar)
        self.profile_card.now_btn.clicked.connect(self.what_now)

        # conversation
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.feed = QWidget(objectName="Feed")
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 4, 6, 4)
        self.feed_lay.setSpacing(8)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        lay.addWidget(self.scroll, 1)
        # an empty chat: a few questions for this character (the first message hides them)
        self.starters = Chips()
        lay.addWidget(self.starters)
        self._next_steps = None      # under the newest answer: play tools, follow-ups or an error's fix
        self._follow = True          # keep the newest content in view (off once an answer outgrows the view)
        self._anchor = None          # the answer being read: stay at its first line
        self.scroll.verticalScrollBar().rangeChanged.connect(self._on_range)

        # tagged cards: "asking about:" + a chip per card (tap a card again or its ✕ to untag)
        self.focus_keys: list[str] = []
        self.focus_bar = QFrame(objectName="FocusBar")
        fb = QHBoxLayout(self.focus_bar)
        fb.setContentsMargins(8, 4, 6, 4)
        fb.setSpacing(6)
        self.focus_label = QLabel(objectName="FocusText")
        fb.addWidget(self.focus_label)
        self.focus_chips = QHBoxLayout()
        self.focus_chips.setSpacing(6)
        fb.addLayout(self.focus_chips, 1)
        clear_all = self._icon_button(theme.ICON["close"])
        clear_all.setToolTip(self.t("untag_all"))
        clear_all.clicked.connect(lambda: self.set_tags([]))
        fb.addWidget(clear_all)
        self.focus_bar.hide()
        lay.addWidget(self.focus_bar)
        SELECTION.picked.connect(self.toggle_tag)

        # input capsule: [camera] field [mic] (send)
        self.capsule = Capsule(objectName="Capsule")
        self.capsule.setFixedHeight(42)
        row = QHBoxLayout(self.capsule)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(2)
        self.recapture_btn = self._icon_button(theme.ICON["camera"])
        self.recapture_btn.clicked.connect(self.recapture)
        row.addWidget(self.recapture_btn)
        self.input = FocusLineEdit(objectName="Input")
        self.input.returnPressed.connect(self._send_typed)
        self.input.textChanged.connect(self._on_text)
        self.input.focus_changed.connect(self.capsule.set_focus_look)
        row.addWidget(self.input, 1)
        self.mic_btn = self._icon_button(theme.ICON["mic"])
        self.mic_btn.clicked.connect(self.mic_clicked.emit)   # click to talk; holding the voice key works too
        row.addWidget(self.mic_btn)
        self.send_btn = QToolButton(objectName="Send", text=theme.ICON["send"])
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(lambda: self.stop_answer() if self.busy else self._send_typed())   # mid-answer: stop
        self.send_btn.setEnabled(False)
        row.addWidget(self.send_btn)
        # what the next question sends: the F9 screenshot goes with the first question only
        self.shot_hint = QLabel(objectName="ShotHint")
        self.shot_hint.setTextFormat(Qt.RichText)
        self.shot_hint.setWordWrap(True)
        self.shot_hint.linkActivated.connect(lambda _link: self.recapture())
        self.shot_hint.hide()
        lay.addWidget(self.shot_hint)
        lay.addWidget(self.capsule)

        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        self.grip.setStyleSheet("background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        m = self.SHADOW
        self.grip.move(self.width() - m - 18 if not self.t.rtl else m + 2, self.height() - m - 18)
        if self.isVisible():
            self._save_timer.start()

    def apply_language(self):
        from . import terms
        self.t = I18n(self.settings["language"] or "he")
        terms.LANG = self.t.lang              # the "?" popups follow a language switch
        self.setLayoutDirection(Qt.RightToLeft if self.t.rtl else Qt.LeftToRight)
        hk_voice = self.settings["hotkey_voice"]
        self._placeholder = self.t("input_placeholder").replace("F10", hk_voice)
        self.input.setPlaceholderText(bidi.plain(self._placeholder, self.t.rtl))
        self.recapture_btn.setToolTip(self.t("recapture"))
        self.settings_btn.setToolTip(self.t("settings"))
        self.saver_badge.setText("🍃 " + self.t("saver_on_badge"))
        self.saver_badge.setToolTip(self.t("saver_hint"))
        self.wish_btn.setToolTip(self.t("wishlist"))
        self.guides_btn.setToolTip(self.t("guides"))
        self.history_btn.setToolTip(self.t("history_tip"))
        self.profile_card.refresh.setToolTip(self.t("refresh_tip"))
        self.profile_card.now_btn.setText(self.t("plan_what_now"))
        self.profile_card.now_btn.setToolTip(self.t("what_now_tip"))
        if getattr(self, "_update_version", None):
            self.show_update(self._update_version, getattr(self, "_update_state", "available"))
        self.profile_card.setToolTip(self.t("switch_character"))
        self.min_btn.setToolTip(self.t("minimize"))
        self.close_btn.setToolTip(self.t("close_chat_tip").replace("F9", self.settings["hotkey_toggle"]))
        self.input.setToolTip(self.t("keys_hint"))
        self.apply_window_prefs()
        self.mic_btn.setToolTip(self.t("mic_tip", key=hk_voice))
        self._on_text(self.input.text())
        self.refresh_profile_chip()
        self._update_shot_hint()
        for card, render in getattr(self, "_notices", []):
            if _alive(card):
                card.set_texts(*render(self.t), self.t.rtl)

    def show_update(self, version: str, state: str = "available", pct: float | None = None):
        """The update bar: available (button) -> downloading (progress) -> installing; failed (retry)."""
        self._update_version, self._update_state = version, state
        t, rtl = self.t, self.t.rtl
        text = {"available": t("update_bar_available", version=version),
                "ready": t("update_bar", version=version),
                "downloading": t("update_downloading", version=version, pct=round(pct or 0)),
                "installing": t("update_installing", version=version),
                "failed": t("update_failed")}[state]
        self.update_label.setText(bidi.plain(text, rtl))
        self.update_btn.setText(bidi.plain(t("update_retry" if state == "failed" else "update_now"), rtl))
        self.update_btn.setVisible(state in ("available", "ready", "failed"))
        self.update_progress.setVisible(state in ("downloading", "installing"))
        if state == "downloading":
            self.update_progress.setRange(0, 1000)
            self.update_progress.setValue(round((pct or 0) * 10))
        elif state == "installing":
            self.update_progress.setRange(0, 0)          # busy: the installer takes over in a moment
        self.update_bar.show()

    def refresh_profile_chip(self):
        WISHLIST.changed.emit()          # the stars follow the active character
        c = self.profiles.active
        self.profile_card.setVisible(c is not None)
        if c:
            self.profile_card.show_character(c, self.profiles.avatar_path(c), self.kb, self.t.rtl)
        self.refresh_plan()
        self.refresh_pins()
        self._refresh_starters()

    # ------------------------------------------------------------------ plan (EXP, tips, "My plan")

    def refresh_pins(self):
        from .. import pins
        c = self.profiles.active
        self.pins_bar.show_pins(pins.items(self.settings, c.id if c else None), self.t, self.t.rtl)

    def pin_answer(self, question: str, answer: str, cid: str | None = None):
        from .. import pins
        c = self.profiles.active
        cid = cid or (c.id if c else None)
        if cid and pins.add(self.settings, cid, question, answer):
            self.refresh_pins()
            self.add_system(self.t("pinned_done"))

    def _unpin(self, answer: str):
        from .. import pins
        c = self.profiles.active
        if c:
            pins.remove(self.settings, c.id, answer)
            self.refresh_pins()

    def copy_character_card(self):
        """The character as a picture on the clipboard, to brag in Discord or WhatsApp."""
        from PySide6.QtWidgets import QApplication
        from .. import plan
        from .pinsview import character_card_image
        c = self.profiles.active
        if not c:
            return
        pm = character_card_image(c, self.profiles.avatar_path(c), self.kb,
                                  plan.progress(self.kb, c.level, c.exp_pct), self.t)
        QApplication.clipboard().setPixmap(pm)
        self.add_system(self.t("copied"))

    def refresh_plan(self):
        from .. import plan
        c = self.profiles.active
        if not c:
            self.tip_strip.show_tip(None, self.t, self.t.rtl)
            return
        self.profile_card.exp.show_progress(plan.progress(self.kb, c.level, c.exp_pct), self.t, self.t.rtl)
        dismissed = (self.settings["tips_dismissed"] or {}).get(c.id, {})
        self.tip_strip.show_tip(plan.tip(self.kb, c, self.t, dismissed), self.t, self.t.rtl)

    def _dismiss_tip(self, kind: str):
        c = self.profiles.active
        if not c:
            return
        data = dict(self.settings["tips_dismissed"] or {})
        data[c.id] = {**data.get(c.id, {}), kind: c.level}
        self.settings["tips_dismissed"] = data
        self.refresh_plan()

    def _shoot(self, hwnd):
        """The game's screenshot, or None."""
        if not hwnd:
            return None
        try:
            return self.shot_provider(hwnd) if self.shot_provider else osapi.capture_game(hwnd)
        except Exception:      # noqa: BLE001 - a failed capture must not break the chat
            import logging
            logging.getLogger(__name__).warning("screenshot failed", exc_info=True)
            return None

    def _step_aside(self, then):
        """The chat is part of the screen: it hides for the shot and always comes back.
        then(hwnd, shot) runs once it is back."""
        self.setWindowOpacity(0.0)

        def shoot():
            try:
                hwnd = osapi.find_game_window() or self.game_hwnd
            except Exception:      # noqa: BLE001 - a failed lookup is just "no game"
                hwnd = self.game_hwnd
            shot = self._shoot(hwnd)          # never raises: the chat always comes back
            self.setWindowOpacity(self.full_opacity())
            then(hwnd, shot)
        QTimer.singleShot(120, shoot)

    def ask_with_screenshot(self, question: str):
        """A fresh screenshot of the game, then the question, so the AI sees where the player is."""
        def ask(hwnd, shot):
            if hwnd:
                self.game_hwnd, self.shot, self.shot_used = hwnd, shot, False
            self.ask(question)
        self._step_aside(ask)

    def what_now(self):
        self.ask_with_screenshot(self.t("what_now_q"))

    def character_menu(self):
        """Click the character card: pick another character or add one, right from the chat."""
        # the click that closes the open menu lands on the card too: don't reopen it
        if time.monotonic() - getattr(self, "_menu_closed_at", 0) < 0.3:
            return
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setLayoutDirection(Qt.RightToLeft if self.t.rtl else Qt.LeftToRight)
        # mid-answer the reply still belongs to the current character
        busy = self.busy or getattr(self, "_syncing", False)
        active = self.profiles.active_id
        # the card already shows the current character: the menu lists only the others to switch to
        others = [c for c in self.profiles.characters if c.id != active]
        for c in others:
            img = character_image(c, self.profiles.avatar_path(c), self.kb)
            a = QAction(QIcon(str(img)) if img else QIcon(), bidi.plain(f"{c.name}  ·  Lv. {c.level} {c.job}",
                                                                           self.t.rtl), menu)
            a.setEnabled(not busy)
            a.triggered.connect(lambda _=False, cid=c.id: self.switch_character(cid))
            menu.addAction(a)
        if others:
            menu.addSeparator()
        if self.profiles.active is not None:
            edit = QAction(theme.glyph_icon("edit"), bidi.plain(self.t("edit_character"), self.t.rtl), menu)
            edit.setEnabled(not busy)
            edit.triggered.connect(lambda: self.edit_character_requested.emit(active))
            menu.addAction(edit)
            delete = QAction(theme.glyph_icon("delete"), bidi.plain(self.t("delete_character"), self.t.rtl), menu)
            delete.setEnabled(not busy)
            delete.triggered.connect(lambda: self.delete_character_requested.emit(active))
            menu.addAction(delete)
            menu.addSeparator()
        add = QAction(theme.glyph_icon("add"), bidi.plain(self.t("add_character"), self.t.rtl), menu)
        add.setEnabled(not busy)
        add.triggered.connect(self.add_character_requested.emit)
        menu.addAction(add)
        share = QAction(theme.glyph_icon("copy"), bidi.plain(self.t("share_character"), self.t.rtl), menu)
        share.triggered.connect(self.copy_character_card)
        share.setEnabled(self.profiles.active is not None)
        menu.addAction(share)
        card = self.profile_card
        menu.setMinimumWidth(card.width())
        menu.exec(card.mapToGlobal(QPoint(0, card.height() + 4)))
        self._menu_closed_at = time.monotonic()

    def switch_character(self, cid: str):
        if cid == self.profiles.active_id:
            return
        self.profiles.set_active(cid)
        self.refresh_profile_chip()
        c = self.profiles.active
        if c:
            self.add_system(self.t("switched_character", name=c.name))

    def _on_text(self, text: str):
        """The field follows what is being typed; send lights up only when there is something to send.
        Mid-answer it is the stop button."""
        d = bidi.direction(text) if text.strip() else ("rtl" if self.t.rtl else "ltr")
        self.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)
        # absolute: in an RTL widget a plain AlignRight means "trailing" = left
        self.input.setAlignment((Qt.AlignRight if d == "rtl" else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter)
        self.send_btn.setText(theme.ICON["stop" if self.busy else "send"])
        self.send_btn.setToolTip(self.t("stop_answer") if self.busy else "")
        self.send_btn.setEnabled(not self._stopping if self.busy else bool(text.strip()))

    # ------------------------------------------------------------------ geometry

    def restore_geometry(self):
        g = self.settings["window"]
        if g:
            rect = QRect(g["x"], g["y"], g["w"], g["h"])
            if any(s.availableGeometry().intersects(rect) for s in QGuiApplication.screens()):
                self.setGeometry(rect)
                return
        self.place_default()

    def place_default(self, near_hwnd: int | None = None):
        """Top-right corner of the game's screen (or the primary screen)."""
        screen = QGuiApplication.primaryScreen()
        rect = osapi.window_rect(near_hwnd) if near_hwnd else None
        if rect:
            s = QGuiApplication.screenAt(QPoint(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2))
            screen = s or screen
        a = screen.availableGeometry()
        w, h = 420, min(640, a.height() - 80)
        self.setGeometry(a.right() - w - 24, a.top() + 60, w, h)

    def save_geometry(self):
        g = self._target_geometry if self._target_geometry is not None else self.geometry()   # mid-grow: its real size
        self.settings["window"] = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}

    # ------------------------------------------------------------------ show / hide

    def _materialize(self, show: bool, on_done=None):
        """The material arrives: opacity and a small scale settle together (critically damped, no bounce)."""
        if self._anim is not None and _alive(self._anim):
            self._anim.stop()           # interruptible: start from wherever it is now
        if self._target_geometry is not None:
            # a grow cut short: from the real size, or every quick F9 twice would shrink the window
            self.setGeometry(self._target_geometry)
            self._target_geometry = None
        g = self.geometry()
        small = QRect(g.x() + round(g.width() * 0.015), g.y() + round(g.height() * 0.015),
                      round(g.width() * 0.97), round(g.height() * 0.97))
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(220 if show else 150)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(self.full_opacity() if show else 0.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        grp = QParallelAnimationGroup(self)
        grp.addAnimation(fade)
        if show:
            self._target_geometry = g
            self.setGeometry(small)
            grow = QPropertyAnimation(self, b"geometry")
            grow.setDuration(240)
            grow.setStartValue(small)
            grow.setEndValue(g)
            grow.setEasingCurve(QEasingCurve.OutCubic)
            grp.addAnimation(grow)
            grp.finished.connect(lambda: setattr(self, "_target_geometry", None))
        if on_done:
            grp.finished.connect(on_done)
        self._anim = grp
        grp.start(QAbstractAnimation.DeleteWhenStopped)

    def full_opacity(self) -> float:
        """What "fully shown" means: the player's chat opacity (Settings, 60-100%)."""
        return max(0.6, min(1.0, (self.settings["chat_opacity"] or 100) / 100))

    def apply_window_prefs(self):
        """Opacity and click-through from Settings. Click-through: the chat stays on screen, clicks go to the game."""
        through = bool(self.settings["click_through"])
        if bool(self.windowFlags() & Qt.WindowTransparentForInput) != through:
            shown = self.isVisible()
            self.setWindowFlag(Qt.WindowTransparentForInput, through)
            if shown:
                self.show()                    # a changed window flag hides the window
                osapi.float_over_fullscreen(int(self.winId()))
                if through:
                    self.add_system(self.t("click_through_on"))
        if self.isVisible() and self.windowOpacity() > 0 and not (self._anim is not None and _alive(self._anim)):
            self.setWindowOpacity(self.full_opacity())

    def open_overlay(self, shot: bytes | None, game_hwnd: int | None):
        if self.settings["click_through"]:
            self.settings["click_through"] = False     # F9 never opens a chat the mouse can't reach
            self.apply_window_prefs()
        self.shot, self.shot_used, self.game_hwnd = shot, False, game_hwnd
        self._update_shot_hint()
        if not self.settings["window"]:
            self.place_default(game_hwnd)
        if self._session_started is None:
            self._session_started = time.time()
            self.stats = SessionStats()
            self.stats.touch(self.profiles.active)
            self._show_last_session()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        osapi.float_over_fullscreen(int(self.winId()))
        osapi.activate_self(int(self.winId()))
        self.input.setFocus()
        self._materialize(True)

    def _show_last_session(self):
        """A new session starts: first, what happened in the previous one."""
        last = self.settings["last_session"]
        if not last:
            return
        self.settings["last_session"] = None

        def details():
            rows = []
            for name, asked in session_questions(last, History).items():
                rows.append((self.t("sess_asked", name=name), "CardName"))
                rows += [("• " + q, "CardStat") for q in asked]
            return rows or [(self.t("sess_no_details"), "CardStat")]
        self._add_widget(SessionCard(self.t("sess_title", minutes=last["minutes"]), session_lines(last, self.t),
                                     self.t.rtl, details, self.t("sess_more"), self.t("sess_less")))

    def close_overlay(self):
        self.bubble.hide()
        if not self.isVisible():
            return
        self.closed.emit()
        def done():
            self.hide()
            self.setWindowOpacity(1.0)
        self._materialize(False, done)
        if self.game_hwnd:
            osapi.focus_window(self.game_hwnd)

    def minimize(self):
        """Shrink to the bubble, which appears where the chat's header was."""
        pos = self.settings["bubble_pos"]
        if pos:
            self.bubble.move(pos["x"], pos["y"])
        else:
            g = self.geometry()
            x = g.left() + self.SHADOW if self.t.rtl else g.right() - self.bubble.width() - self.SHADOW
            self.bubble.move(x, g.top() + self.SHADOW)
        self.close_overlay()
        self.bubble.show()
        self.bubble.raise_()

    def restore_from_bubble(self):
        self.bubble.hide()
        hwnd = osapi.find_game_window()
        self.open_overlay(self._shoot(hwnd) if self.shot_provider else None, hwnd)

    def toggle(self, shot_provider):
        self.shot_provider = shot_provider
        if self.isVisible() and self.windowOpacity() > 0.5:
            self.close_overlay()
        else:
            self.bubble.hide()
            hwnd = osapi.find_game_window()
            self.open_overlay(self._shoot(hwnd), hwnd)

    def keyPressEvent(self, e):
        # Esc stops a running answer, else closes the chat; ↑ in an empty field brings the last question back;
        # Ctrl+F searches past chats
        from PySide6.QtGui import QKeySequence
        if e.key() == Qt.Key_Escape:
            self.stop_answer() if self.busy else self.close_overlay()
            return
        if e.key() == Qt.Key_Up and not self.input.text() and getattr(self, "_last_question", ""):
            self.input.setText(self._last_question)
            self.input.setFocus()
            return
        if e.matches(QKeySequence.Find):
            self.history_requested.emit()
            return
        super().keyPressEvent(e)

    def _update_shot_hint(self):
        """Fresh screenshot: it goes with the next question. Used: say so, with a one-click retake.
        No game open: explain how screenshots work, so the player knows before it matters."""
        if not self.game_hwnd and not self.shot:
            text = self.t("shot_hint_no_game")
        elif self.shot and not self.shot_used:
            text = self.t("shot_hint_ready")
        else:
            text = self.t("shot_hint_used") + f" <a href='shot:now' style='color:{theme.ORANGE_DEEP}; " \
                                               f"text-decoration:none;'><b>{self.t('shot_hint_retake')}</b></a>"
        import re
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        d = "rtl" if self.t.rtl else "ltr"
        from .. import glossary          # the same orange "?" badge as beside game terms
        self.shot_hint.setText(f"<div dir='{d}' align='{'right' if self.t.rtl else 'left'}'>{glossary.MARK}&nbsp; {text}</div>")
        self.shot_hint.show()

    def recapture(self):
        self._step_aside(self._recaptured)

    def _recaptured(self, hwnd, shot):
        self.game_hwnd, self.shot, self.shot_used = hwnd, shot, False
        self.add_system("✓ " + self.t("recaptured")) if self.shot else self._game_notice("sync_no_game")
        self._update_shot_hint()

    def _game_notice(self, key: str):
        """No game window: say so, with the way to fix it one tap away (windowed / borderless mode)."""
        self.add_notice(lambda t: t(key), lambda t: t("fix_game"), lambda: self.add_system(self.t("game_help")))

    # ------------------------------------------------------------------ feed

    MAX_ROWS = 150      # a long session keeps only the newest rows (the history window has every answer)

    def _add_widget(self, w: QWidget):
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, w)
        self._trim_feed()
        # new content fades in rather than popping
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", w)
        a.setDuration(180)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.finished.connect(lambda: w.setGraphicsEffect(None))
        a.start(QAbstractAnimation.DeleteWhenStopped)

    def _trim_feed(self):
        i = 0
        while self.feed_lay.count() - 1 > self.MAX_ROWS:
            w = self.feed_lay.itemAt(i).widget()
            if self._pending_bubble is not None and w.isAncestorOf(self._pending_bubble):
                if self.busy:
                    i += 1              # the answer being written stays
                    continue
                self._pending_bubble = None
            if w is self._anchor:
                self._anchor = None
            self.feed_lay.takeAt(i)
            w.hide()
            w.deleteLater()

    def clear_feed(self):
        self._anchor = None
        self._pending_bubble = None
        while self.feed_lay.count() > 1:
            w = self.feed_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._next_steps = None
        self._refresh_starters()

    def _refresh_starters(self):
        """Questions to start with, while the chat has no messages (new character, cleared history, first open)."""
        from .. import suggest
        self.starters.clear()
        talk = any(isinstance(self.feed_lay.itemAt(i).widget(), BubbleRow) for i in range(self.feed_lay.count() - 1))
        if talk:
            self.starters.hide()
            return
        self.starters.set_title(self.t("sug_title"), self.t.rtl)
        for q in suggest.starters(self.kb, self.profiles.active, self.t):
            self.starters.add(q, lambda q=q: self.ask(q), "NowChip", self.t.rtl)
        self.starters.show()

    def _drop_next_steps(self):
        if self._next_steps is not None and _alive(self._next_steps):
            self._next_steps.hide()
            self._next_steps.deleteLater()
        self._next_steps = None

    def _add_next_steps(self, question: str, entities: list[str], groups: list | None = None, fix=None):
        """Under the newest answer: an error's one-tap fix, or the play-tools page it belongs to and follow-up
        questions about its main card. Older answers lose theirs."""
        from .. import suggest
        self._drop_next_steps()
        t, rtl, chips = self.t, self.t.rtl, Chips()
        if fix:
            label, action = fix
            do = {"retry": lambda: self._ask_tagged(question, self._asked_focus, again=True),
                  "settings": lambda: self.settings_section_requested.emit("ai"),
                  "saver": self.saver_requested.emit}[action]
            chips.add(t.p(label, self.settings["provider"]), do, "NowChip", rtl)
        else:
            page = suggest.tools_page(question, entities)
            if page:
                chips.add(t("open_in_tools", page=t(f"tool_{page}")), lambda: self.tools_page_requested.emit(page),
                          "NowChip", rtl)
            fu = suggest.follow_ups(entities, groups)
            for k in fu[1] if fu else []:
                if k != "fu_level" or self.profiles.active:
                    chips.add(t(k), lambda q=t(k), key=fu[0]: self._ask_tagged(q, [key]), "SubChip", rtl)
        if chips.count():
            self._add_widget(chips)
            self._next_steps = chips

    def _ask_tagged(self, question: str, keys: list[str], again: bool = False):
        """Ask about these cards (the tagging the player does by tapping a card), then put their own tags back."""
        before = list(self.focus_keys)
        self.set_tags(keys)
        self.ask(question, force_claude=again)
        self.set_tags(before)

    MAX_TAGS = 5

    def toggle_tag(self, key: str):
        tags = list(self.focus_keys)
        if key in tags:
            tags.remove(key)
        elif self.kb.get(key):
            tags = (tags + [key])[-self.MAX_TAGS:]
        self.set_tags(tags)

    def set_tags(self, keys: list[str]):
        """Tag cards to ask about; the bar shows a chip per card."""
        self.focus_keys = [k for k in keys if self.kb.get(k)]
        while self.focus_chips.count():
            w = self.focus_chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        for k in self.focus_keys:
            chip = QPushButton(objectName="TagChip")
            chip.setIcon(QIcon(str(self.kb.picture(k))))
            chip.setText(self.kb.get(k)["name"] + "  ✕")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(self.t("untag"))
            chip.clicked.connect(lambda _=False, k=k: self.toggle_tag(k))
            self.focus_chips.addWidget(chip)
        self.focus_chips.addStretch(1)
        self.focus_label.setText(bidi.plain(self.t("asking_about_short"), self.t.rtl))
        self.focus_bar.setVisible(bool(self.focus_keys))
        if self.focus_keys:
            self.input.setFocus()
        SELECTION.changed.emit(self.focus_keys)

    def set_focus(self, key: str):   # kept for callers that tag a single card
        self.set_tags([key] if key else [])

    def add_bubble(self, text: str, role: str, tag: str = "") -> Bubble:
        self.starters.hide()                 # the conversation started
        b = Bubble(text, role, self.t.rtl, tag)
        self._add_widget(BubbleRow(b, self.t.rtl))
        return b

    def add_system(self, text: str):
        self._add_widget(SystemLine(text))

    def add_notice(self, text, action, on_click) -> None:
        """text / action: a string, or a function of I18n that builds it (then a language switch
        shows the notice in the new language too)."""
        def render(t):
            return (text(t) if callable(text) else text), (action(t) if callable(action) else action)
        card = NoticeCard(*render(self.t), self.t.rtl)
        card.clicked.connect(on_click)
        if callable(text) or callable(action):
            self._notices = [n for n in getattr(self, "_notices", []) if _alive(n[0])] + [(card, render)]
        self._add_widget(card)

    def add_cards(self, keys: list[str]):
        if len(keys) <= 2:
            for k in keys:
                self._add_widget(EntityCard(self.kb, k, self.t.lang))
            return
        # the subject (monster, NPC, map, quest) stays a full card; the list (drops, rewards) becomes tiles
        heads = [k for k in keys if k.split("/")[0] in ("monster", "npc", "map", "quest")][:1]
        rest = [k for k in keys if k not in heads]
        for k in heads:
            self._add_widget(EntityCard(self.kb, k, self.t.lang))
        # tiles go in titled groups, so nothing looks like it belongs to the card above unless it does
        groups: dict[str, list[str]] = {}
        if heads and heads[0].startswith("monster/"):
            groups[self.t("tiles_drops", name=self.kb.get(heads[0])["name"])] = []   # its drops first
        drops = set(self.kb.monster_drops(heads[0])) if heads and heads[0].startswith("monster/") else set()
        for k in rest:
            if k in drops:
                title = self.t("tiles_drops", name=self.kb.get(heads[0])["name"])
            else:
                kind = "tiles_" + k.split("/")[0]
                title = self.t(kind if kind in STRINGS else "tiles_other")
            groups.setdefault(title, []).append(k)
        for title, ks in groups.items():
            if ks:
                self._add_widget(TileGrid(self.kb, ks, title))

    def add_confirm(self, text: str, on_yes):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SystemLine(text), 1)
        yes = QPushButton(self.t("yes"), objectName="Chip")
        no = QPushButton(self.t("no"), objectName="Chip")
        yes.clicked.connect(lambda: (on_yes(), row.setDisabled(True)))
        no.clicked.connect(lambda: row.setDisabled(True))
        lay.addWidget(yes)
        lay.addWidget(no)
        self._add_widget(row)

    # ------------------------------------------------------------------ asking

    def _send_typed(self):
        q = self.input.text().strip()
        if q and self.ask(q):
            self.input.clear()

    def ask(self, question: str, force_claude: bool = False) -> bool:
        """Ask (instant answer or Claude). False when nothing was asked (busy, empty)."""
        if self.busy or getattr(self, "_syncing", False) or not question.strip():
            return False
        self._last_question = question
        c = self.profiles.active
        self._asked_cid = c.id if c else None
        history = History(c.id) if c else None
        focus = list(self.focus_keys)
        self._asked_focus = focus
        self._drop_next_steps()
        focus_name = ", ".join(self.kb.get(k)["name"] for k in focus)
        if not force_claude:          # "Ask Claude anyway" re-asks a question already in the chat
            self.add_bubble(question, "user", focus_name)
            if self.stats:
                self.stats.question(c)     # once per question, however it gets answered
            if not focus and self.settings["instant_answers"]:
                qa = quick.answer(question, self.kb, self.t)
                if qa:
                    if history:
                        history.append("user", question)
                    self._show_quick(qa, question, history)
                    return True
        shot = None if self.shot_used else self.shot
        self._question_shot = shot
        if shot is None and not self.shot_used and not self.game_hwnd:
            self._game_notice("no_game")
        self.shot_used = True
        self._update_shot_hint()
        if history:   # again for "Ask Claude anyway", so history search pairs the question with this answer
            history.append("user", f"[about {focus_name}] {question}" if focus_name else question)
        self._anchor = None
        self._follow = True
        self._pending_bubble = self.add_bubble(self.t("status_shot" if shot else "thinking"), "assistant")
        self._answer_started = False          # until text streams, the bubble says what the AI is doing
        self.busy = True
        self._on_text(self.input.text())      # send turns into stop

        self._thread = QThread(self)
        self._worker = AskWorker(self.brain, question, c, history, shot, focus)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.delta.connect(self._on_delta)
        self._worker.status.connect(self._on_status)
        # a bound method of this QObject → Qt queues the call onto the GUI thread.
        # (a lambda here would run in the worker thread and build widgets there: crash + stray window)
        self._pending_history = history
        self._worker.done.connect(self._on_done_main)
        self._worker.done.connect(self._thread.quit)
        # one thread per question: both go once it ends
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self.brain.begin()          # here, not in the worker: a Stop pressed before it runs still counts
        self._thread.start()
        return True

    def _read_limits_after_answer(self):
        """ChatGPT doesn't report its plan usage with the answer: read it in the background, so the
        same "running low" heads-up shows for both AIs."""
        import threading

        from .. import providers
        ai = providers.get(self.settings["provider"])
        if not ai.reports_usage or self.settings.api_key_mode(ai.name) or self.settings["no_ai"]:
            return
        if type(ai).read_limits is providers.base.Provider.read_limits:
            return                      # this AI already reported it with the answer
        if not getattr(self, "_limits_wired", False):
            self.limits_read.connect(self._note_usage)
            self._limits_wired = True
        threading.Thread(target=lambda: self.limits_read.emit(ai.read_limits()), daemon=True).start()

    def _note_usage(self, limits: dict | None):
        """Remember the plan usage; when the 5-hour window runs low, say so once (with the way to save)."""
        from .. import usage
        if not limits:
            return
        p = self.settings["provider"]
        usage.record(self.settings, limits, provider=p)
        lvl = usage.level(self.settings, provider=p)
        w = usage.current(self.settings, provider=p).get("five_hour", {})
        if lvl == "ok" or self.settings["usage_warned"] == [w.get("resets"), lvl]:
            return
        if lvl == "high" and self.settings["saver_mode"]:
            return              # already saving: only the "almost used up" warning matters
        self.settings["usage_warned"] = [w.get("resets"), lvl]
        def text(t):
            return t.p("usage_high" if lvl == "high" else "usage_critical", p, pct=round(w["used"] * 100),
                       at=usage.reset_clock(w.get("resets")))
        if self.settings["saver_mode"]:
            self.add_system(text(self.t))
        else:
            self.add_notice(text, lambda t: t("saver_turn_on"), self.saver_requested.emit)

    def show_saver_badge(self, on: bool):
        self.saver_badge.setVisible(on)

    def _show_quick(self, qa, question: str, history):
        """An instant answer from the KB, with the way to Claude one tap away."""
        self._anchor = None
        self._follow = True
        b = self.add_bubble(qa.text, "assistant")
        b.add_pin(lambda: self.pin_answer(question, qa.text), self.t("pin"))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(4, 0, 4, 0)
        rl.setSpacing(8)
        rl.addWidget(QLabel(bidi.plain(self.t("quick_badge"), self.t.rtl), objectName="SystemLine"))
        again = QPushButton(bidi.plain(self.t.p("quick_ask_ai", self.settings["provider"]), self.t.rtl),
                            objectName="Link")
        again.setCursor(Qt.PointingHandCursor)
        again.clicked.connect(lambda: again.setEnabled(not self.ask(question, force_claude=True)))
        rl.addWidget(again)
        rl.addStretch(1)
        self._add_widget(row)
        if history:
            history.append("assistant", qa.text, qa.entities)
        for g in qa.drop_groups:
            self._add_widget(DropGroupCard(self.kb, g["monster"], g["items"]))
        if qa.entities and not qa.drop_groups:     # the drop groups already show the item
            self.add_cards(qa.entities)
        self._add_next_steps(question, qa.entities, qa.drop_groups)

    def _on_range(self, _lo: int, hi: int):
        bar = self.scroll.verticalScrollBar()
        if self._anchor is not None:
            bar.setValue(min(hi, self._anchor_top()))
        elif self._follow:
            bar.setValue(hi)

    def _anchor_top(self) -> int:
        row = self._anchor
        return max(0, row.mapTo(self.feed, row.rect().topLeft()).y() - 8) if row else 0

    def _keep_answer_readable(self):
        """Once the answer (plus what follows it) is taller than the view, pin its first line to the top."""
        if not self._pending_bubble:
            return
        row = self._pending_bubble.parentWidget()
        top = row.mapTo(self.feed, row.rect().topLeft()).y()
        below = self.feed.height() - top
        if below > self.scroll.viewport().height() - 16:
            self._anchor = row
            self.scroll.verticalScrollBar().setValue(self._anchor_top())

    def _on_status(self, code: str):
        """What the AI is doing before it writes: searching the database, reading about a monster…"""
        if not (self._pending_bubble and self.busy) or self._stopping or self._answer_started:
            return
        kind, _, key = code.partition(":")
        e = self.kb.get(key) if key else None
        text = self.t("status_search") if kind == "search" else \
            self.t("status_read", name=e["name"]) if e else self.t("status_read_any")
        self._pending_bubble.set_text(text, explain=False)

    def _on_delta(self, text: str):
        if self._pending_bubble and text and not self._stopping:
            self._answer_started = True
            self._delta_text = text
            if not self._delta_timer.isActive():
                self._delta_timer.start()

    def _render_delta(self):
        # the "?" beside game terms waits for the whole answer: annotating every token was the cost
        if self._pending_bubble and self.busy and not self._stopping:
            self._pending_bubble.set_text(_visible(self._delta_text), explain=False)
            QTimer.singleShot(0, self._keep_answer_readable)

    def stop_answer(self):
        """Stop (the send button mid-answer, or Esc): the AI stops and the chat is free again."""
        if not self.busy or self._stopping:
            return
        self._stopping = True
        self._delta_timer.stop()
        if self._pending_bubble:
            self._pending_bubble.set_text(self.t("answer_stopped"))
        self._on_text(self.input.text())
        self.brain.cancel()

    SYNC_QUESTION = ("[Profile sync, not a chat question] Look at the screenshot and read MY character's current "
                     "level, job and EXP bar percentage (the HUD shows them), and if the stat window is open, its "
                     "Accuracy, damage range and max HP/MP. Reply with one short line in the "
                     "profile's language, then @@META@@ with profile_update (level, job, base_class if visible, "
                     "exp_percent, stats) and avatar_box. If the game or the character is not visible, say so briefly "
                     "and leave profile_update empty.")

    def sync_profile(self):
        if getattr(self, "_syncing", False):
            return              # the read already running answers this request too
        if self.busy:
            self.sync_finished.emit(False)       # mid-answer: say so, or an EXP reading waits for it forever
            return
        self._syncing = True
        self.profile_card.set_busy(True, self.t("syncing"))
        self._step_aside(self._sync_capture)

    def _sync_capture(self, _hwnd, shot):
        if not shot:
            self._syncing = False
            self.profile_card.set_busy(False)
            self._game_notice("sync_no_game")
            self.sync_finished.emit(False)
            return
        self._sync_shot = shot
        self._sync_thread = QThread(self)
        self._sync_cid = self.profiles.active_id
        self._sync_worker = AskWorker(self.brain, self.SYNC_QUESTION, self.profiles.active, None, shot)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.done.connect(self._on_sync_done)      # bound method → runs on the GUI thread
        self._sync_worker.done.connect(self._sync_thread.quit)
        self._sync_thread.finished.connect(self._sync_worker.deleteLater)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self.brain.begin()
        self._sync_thread.start()

    def _on_sync_done(self, ans: Answer):
        self._syncing = False
        self.profile_card.set_busy(False)
        if ans.error:
            self.add_system(self.t("err_generic"))
            self.sync_finished.emit(False)
            return
        if self.profiles.active_id != getattr(self, "_sync_cid", None):
            self.sync_finished.emit(False)
            return             # the player switched character meanwhile: this read belongs to the other one
        changes = self.profiles.apply_update(ans.profile_update or {})
        if ans.avatar_box:
            self._update_avatar(self._sync_shot, ans.avatar_box)
        if changes:
            self._show_changes(changes)
        else:
            self.add_system(self.t("sync_nothing") if ans.profile_update or ans.avatar_box
                            else self.t("sync_not_found"))
        self.refresh_profile_chip()
        self.sync_finished.emit(bool(ans.profile_update))

    def _on_done_main(self, ans: Answer):
        self._on_done(ans, self._pending_history)

    def _on_done(self, ans: Answer, history: History | None):
        self.busy = False
        stopped, self._stopping = self._stopping, False
        self._delta_timer.stop()
        self._on_text(self.input.text())
        self._note_usage(ans.limits)
        self._read_limits_after_answer()
        if ans.model:
            self.settings["last_model"] = {**(self.settings["last_model"] or {}), self.settings["provider"]: ans.model}
        if stopped:
            return                  # the player stopped it: whatever came back is dropped
        if self._pending_bubble is None:          # the feed was cleared meanwhile
            self._pending_bubble = self.add_bubble("", "assistant")
        if ans.error:
            import logging
            logging.getLogger(__name__).warning("answer failed: %s", ans.error)
            key, fix = error_view(ans.error, self.settings["saver_mode"])
            self._pending_bubble.set_text(self.t.p(key, self.settings["provider"]))
            self._add_next_steps(getattr(self, "_last_question", ""), [], fix=fix)
            return
        self._pending_bubble.set_text(ans.text)
        q = getattr(self, "_last_question", "")
        self._pending_bubble.add_pin(lambda q=q, a=ans.text: self.pin_answer(q, a), self.t("pin"))
        self._answer_footer(q, ans)
        QTimer.singleShot(0, self._keep_answer_readable)
        QTimer.singleShot(250, self._keep_answer_readable)   # after the cards' layout settles
        if history:
            history.append("assistant", ans.text, ans.entities)
        for g in ans.drop_groups:
            self._add_widget(DropGroupCard(self.kb, g["monster"], g["items"]))
        if ans.entities:
            self.add_cards(ans.entities)
        self._add_next_steps(q, ans.entities, ans.drop_groups)
        if self.profiles.active_id == getattr(self, "_asked_cid", None):
            self._apply_profile_update(ans.profile_update)
            if ans.avatar_box and getattr(self, "_question_shot", None):
                self._update_avatar(self._question_shot, ans.avatar_box)

    def _answer_footer(self, question: str, ans: Answer):
        """Beside the 📌: 👍/👎 (kept on this PC only) and, on an API key, what the answer cost."""
        import threading

        from .. import costs, feedback
        row = footer(self._pending_bubble)
        rating = Rating(self.t)
        model, lang = ans.model or getattr(self.brain, "model", None), self.t.lang
        rating.rated.connect(lambda r: threading.Thread(
            target=feedback.add, args=(question, ans.text, r, ans.entities, model, lang), daemon=True).start())
        row.insertWidget(row.count() - 1, rating)
        if ans.cost_usd and getattr(self.brain, "api_key", None):     # a subscription has no per-answer cost
            cost = QLabel(costs.label(ans.cost_usd), objectName="SystemLine")
            cost.setToolTip(self.t("cost_tip"))
            row.insertWidget(0, cost)
            threading.Thread(target=costs.add, args=(ans.cost_usd,), daemon=True).start()

    def _apply_profile_update(self, update: dict):
        c = self.profiles.active
        if not c or not update:
            return
        new_level = update.get("level")
        if isinstance(new_level, int) and new_level < c.level:
            # a lower level usually means the screenshot showed another character: ask first
            rest = {k: v for k, v in update.items() if k != "level"}
            self._show_changes(self.profiles.apply_update(rest))
            cid = c.id
            self.add_confirm(self.t("confirm_profile", level=new_level),
                             lambda: self._show_changes(self.profiles.apply_update({"level": new_level}))
                             if self.profiles.active_id == cid else None)
            return
        self._show_changes(self.profiles.apply_update(update))

    def _update_avatar(self, shot_jpeg: bytes, box: list) -> None:
        """Crop the player's own sprite (box from the AI, fractions of the image) into the portrait."""
        import io
        from PIL import Image
        try:
            img = Image.open(io.BytesIO(shot_jpeg)).convert("RGB")
            W, H = img.size
            x, y, w, h = box
            if not (0 <= x < 1 and 0 <= y < 1 and 0.005 < w < 0.5 and 0.01 < h < 0.6):
                return
            pad_w, pad_h = w * 0.25, h * 0.12
            left, top = max(0, (x - pad_w) * W), max(0, (y - pad_h) * H)
            right, bottom = min(W, (x + w + pad_w) * W), min(H, (y + h + pad_h) * H)
            crop = img.crop((int(left), int(top), int(right), int(bottom)))
            side = max(crop.size)
            square = Image.new("RGB", (side, side), crop.getpixel((0, 0)))
            square.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
            square = square.resize((128, 128), Image.LANCZOS)
            buf = io.BytesIO()
            square.save(buf, "PNG")
            self.profiles.set_avatar(buf.getvalue())
            self.refresh_profile_chip()
        except Exception:
            pass

    def _show_changes(self, changes):
        if changes:
            self.profile_changed.emit()        # the play tools (stats, EXP meter) follow the profile
        changes = [ch for ch in changes if ch[0] != "exp"]     # the EXP bar shows it; no chat line per percent
        self.refresh_plan()
        labels = {"level": "level", "job": "job", "base_class": "job", "map": "map",
                  "quest+": "quest_started", "quest-": "quest_done", "note": "note", "stats": "stats_word"}
        for field, value in changes:
            self.add_system(self.t("profile_updated", what=f"{self.t(labels[field])} {value}"))
            if self.stats:
                self.stats.change(self.profiles.active, field, value)
        if changes:
            self.refresh_profile_chip()

    # ------------------------------------------------------------------ voice

    def voice_state(self, state: str):
        """listening | transcribing | idle | loading"""
        self.mic_btn.setProperty("active", "true" if state.startswith("listening") else "false")
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)
        text = {"listening": self.t("listening", key=self.settings["hotkey_voice"]),
                "transcribing": self.t("transcribing"),
                "loading": self.t("voice_loading")}.get(state, self._placeholder)
        self.input.setPlaceholderText(bidi.plain(text, self.t.rtl))

    def voice_text(self, text: str, send: bool):
        text = text.strip()
        if not text:
            return
        if send and self.ask(text):
            return
        else:
            self.input.setText(text)
            self.input.setFocus()

    def save_session_summary(self):
        if self.stats:
            summary = self.stats.summary(self.profiles)
            if summary:
                self.settings["last_session"] = summary
            self.stats = None

    def end_session(self) -> str:
        """Transcript of this session (for the long-term summary)."""
        c = self.profiles.active
        if not c or self._session_started is None:
            return ""
        recent = [r for r in History(c.id).recent(60) if r["t"] >= self._session_started]
        self._session_started = None
        self.save_session_summary()
        return "\n".join(f"{r['role']}: {r['text']}" for r in recent)
