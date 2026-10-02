"""The chat's extras: starter and follow-up questions, "what the AI is doing", cost, 👍/👎, errors with a fix,
shortcuts, opacity and click-through."""
import json
import sys
import threading

import pytest
from test_ui_overlay import wait  # also stands in for the OS layer (no game) off Windows

from maplehelper import costs, feedback, store, suggest
from maplehelper.brain import Answer
from maplehelper.i18n import I18n
from maplehelper.store import Character

EN = I18n("en")


# ------------------------------------------------------------------ what to offer (no Qt)

def test_starters_fit_the_character(kb, monkeypatch):
    beginner = Character("a", "A", "Beginner", "Beginner", 8)
    qs = suggest.starters(kb, beginner, EN)
    assert qs[0] == EN("sug_train") and EN("sug_job_pick", level=10) in qs and qs[-1] == EN("sug_quests")
    warrior = Character("b", "B", "Warrior", "Warrior", 15, map="Henesys")
    assert EN("sug_map", map="Henesys") in suggest.starters(kb, warrior, EN)       # no advancement close: the map
    assert not any("job" in q for q in suggest.starters(kb, Character("c", "C", "Warrior", "Warrior", 12), EN))
    monkeypatch.setattr(kb, "monster_drops", lambda key: ["item/2000000"] if key == "monster/1210100" else [])
    qs = suggest.starters(kb, Character("d", "D", "Beginner", "Beginner", 6), EN)
    assert EN("sug_drops", name="Pig") in qs and len(qs) == 4
    assert suggest.starters(kb, None, EN) == [EN("sug_train"), EN("sug_quests")]


def test_follow_ups_follow_the_main_card():
    assert suggest.follow_ups(["item/2000000", "monster/100101"]) == ("monster/100101",
                                                                     ["fu_where", "fu_level", "fu_drops"])
    assert suggest.follow_ups(["item/2000000"]) == ("item/2000000", ["fu_who_drops", "fu_buy"])
    assert suggest.follow_ups(["map/100000000"])[1] == ["fu_get_there", "fu_map_mobs"]
    assert suggest.follow_ups(["quest/1000"])[1] == ["fu_quest_how"]
    assert suggest.follow_ups([], [{"monster": "monster/100101", "items": ["item/2000000"]}])[0] == "monster/100101"
    assert suggest.follow_ups(["skill/warrior__power-strike"]) is None
    assert suggest.follow_ups([]) is None


@pytest.mark.parametrize("question,entities,page", [
    ("איפה כדאי לי לאמן בלבל 20?", [], "train"),
    ("Where should I train now?", [], "train"),
    ("how many hits to kill a Pig", [], "calc"),
    ("למה אני מפספס הרבה?", [], "calc"),
    ("כמה עולה Red Potion", [], "prices"),
    ("which quests can I take", [], "quests"),
    ("מה צריך בשביל קראפטינג של כפפות", [], "crafting"),
    ("how should I spend my AP", [], "build"),
    ("what does Mano drop", ["monster/100100"], None),
    ("tell me about this", ["quest/1000"], "quests"),
])
def test_the_play_tools_page_an_answer_belongs_to(question, entities, page):
    assert suggest.tools_page(question, entities) == page


def test_error_codes_say_what_to_do_and_offer_the_fix():
    from maplehelper.ui.overlay import error_view
    assert error_view("not_logged_in") == ("err_not_logged_in", ("sign_in", "settings"))
    assert error_view("no_ai") == ("err_no_ai", ("fix_connect_ai", "settings"))
    assert error_view("launch_failed: [Errno 2] no such file") == ("err_launch_failed", ("fix_settings", "settings"))
    assert error_view("usage_limit") == ("err_usage_limit", ("saver_turn_on", "saver"))
    assert error_view("usage_limit", saver_on=True) == ("err_usage_limit", None)      # saving already
    assert error_view("timeout")[1] == ("retry", "retry")
    assert error_view("internal: boom") == ("err_generic", ("retry", "retry"))
    assert EN("err_no_ai") == ("Connect Claude or ChatGPT to get AI answers. Instant answers and play tools work "
                               "without it.")


# ------------------------------------------------------------------ local files

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_the_cost_ledger_counts_per_month(data_dir):
    oct_, nov = 1790000000.0, 1792700000.0          # Sep/Oct 2026 and Oct/Nov 2026, whatever the time zone
    costs.add(0.004, oct_)
    costs.add(0.0015, oct_)
    costs.add(0.5, nov)
    costs.add(0)                                    # nothing to count
    assert costs.month_total(oct_) == pytest.approx(0.0055)
    assert costs.month_total(nov) == pytest.approx(0.5)
    assert json.loads((data_dir / "costs.json").read_text()) == {costs.month(oct_): 0.0055, costs.month(nov): 0.5}
    assert costs.label(0.0041) == "$0.004" and costs.label(1.234) == "$1.23"


def test_ratings_stay_on_this_pc_and_keep_the_newest(data_dir, monkeypatch):
    monkeypatch.setattr(feedback, "KEEP", 3)
    for i in range(5):
        feedback.add(f"q{i}", f"a{i}", "down" if i % 2 else "up", ["monster/100100"], "claude-sonnet-5", "en")
    rows = feedback.load()
    assert [r["question"] for r in rows] == ["q2", "q3", "q4"]
    assert set(rows[0]) == {"question", "answer", "rating", "entities", "model", "date", "lang"}


def test_thumbs_down_become_draft_eval_cases(kb, data_dir, tmp_path):
    import eval_answers
    import feedback_evals
    feedback.add("where does Blue Snail live", "In Ellinia.", "down", [], "m", "en")
    feedback.add("where does Blue Snail live", "Still Ellinia.", "down", [], "m", "en")     # once
    feedback.add("how much is a Red Potion", "50 mesos", "up", [], "m", "en")             # liked: not a case
    feedback.add("למה אני מת כל הזמן?", "תשובה", "down", [], "m", "he")
    feedback.add("how much hp does mano have", "lots", "down", [], "m", "en")             # answers.json has it
    existing = eval_answers.load_cases()
    cases = feedback_evals.drafts(feedback.load(), existing, kb)
    assert [c["question"] for c in cases] == ["where does Blue Snail live", "למה אני מת כל הזמן?"]
    snail, other = cases
    assert snail["kind"] == "where" and snail["checks"] == {"must_mention": ["Blue Snail"]}
    assert "In Ellinia." in snail["note"]
    assert other["lang"] == "he" and other["checks"] == {}
    problems = eval_answers.validate_cases(cases)
    assert problems == [f"{other['id']}: checks must be a non-empty object"]      # the one to fill by hand
    out = tmp_path / "drafts.json"
    assert feedback_evals.main([str(feedback.path()), "--out", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["cases"]) == 2


# ------------------------------------------------------------------ what the AI is doing (Claude's stream)

def test_tool_calls_become_a_status_without_their_arguments():
    from maplehelper.providers.claude import tool_status
    assert tool_status({"name": "Grep", "input": {"pattern": "Mano"}}) == "search"
    assert tool_status({"name": "Glob", "input": {"pattern": "pages/**"}}) == "search"
    assert tool_status({"name": "Read", "input": {"file_path": "C:\\kb\\pages\\monster\\100100.md"}}) == \
        "read:monster/100100"
    assert tool_status({"name": "Read", "input": {"file_path": "/kb/pages/guide/exp-table.md"}}) == "read:guide/exp-table"
    assert tool_status({"name": "Read", "input": {"file_path": "/kb/index.json"}}) == "read"
    assert tool_status({"name": "Bash", "input": {}}) is None


@pytest.mark.skipif(sys.platform == "win32", reason="the fake CLI is a POSIX script")
def test_claude_reports_its_lookups_while_it_works(kb_copy, tmp_path, monkeypatch):
    from test_core_providers import brain_for, fake_cli
    events = [{"type": "assistant", "message": {"content": [
                  {"type": "tool_use", "name": "Grep", "input": {"pattern": "Snail"}}]}},
              {"type": "assistant", "message": {"content": [
                  {"type": "tool_use", "name": "Read", "input": {"file_path": "pages/monster/100100.md"}}]}},
              {"type": "result", "result": "Hi.\n@@META@@\n{}"}]
    body = "sys.stdin.read()\n" + "".join(f"print({json.dumps(json.dumps(e))})\n" for e in events)
    b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, body))
    seen = []
    assert b.ask("hi", None, None, None, on_status=seen.append).text == "Hi."
    assert seen == ["search", "read:monster/100100"]
    assert b.ask("hi", None, None, None).text == "Hi."           # no callback, no problem


# ------------------------------------------------------------------ the chat window

class Brain:
    """Answers each question with the next of `answers` (an Answer); records what it was asked."""

    def __init__(self, *answers, status=None, api_key=None):
        self.answers, self.status, self.api_key, self.model = list(answers), status, api_key, "sonnet"
        self.asked = []
        self.go = threading.Event()
        self.go.set()

    def ask(self, question, character, history, shot, on_delta=None, focus=None, on_status=None):
        self.asked.append((question, list(focus or [])))
        if self.status and on_status:
            on_status(self.status)
        self.go.wait(5)
        return self.answers.pop(0) if self.answers else Answer(text="ok")

    def cancel(self):
        self.go.set()

    def begin(self):
        pass


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def chat(qapp, isolated_store, kb, data_dir):
    from maplehelper.ui.overlay import Overlay
    s = isolated_store.Settings()
    s["language"] = "en"
    s["instant_answers"] = False
    profiles = isolated_store.Profiles()
    profiles.add("Kiwi", "Beginner", "Beginner", 8)
    ov = Overlay(s, profiles, kb, Brain())
    yield ov
    ov.close()


def ask_and_wait(qapp, ov, question):
    assert ov.ask(question)
    assert wait(qapp, lambda: not ov.busy)
    qapp.processEvents()


def chip_texts(w):
    from PySide6.QtWidgets import QPushButton
    return [b.text() for b in w.findChildren(QPushButton)] if w is not None else []


def test_an_empty_chat_offers_questions_for_the_character(qapp, chat):
    assert not chat.starters.isHidden()
    assert chip_texts(chat.starters)[:2] == [EN("sug_train"), EN("sug_job_pick", level=10)]
    chat.starters.flow.itemAt(0).widget().click()              # tapping one asks it
    assert wait(qapp, lambda: not chat.busy)
    assert chat.brain.asked[0][0] == EN("sug_train")
    assert chat.starters.isHidden()
    chat.clear_feed()                                          # history cleared: they come back
    assert not chat.starters.isHidden()


def test_follow_ups_sit_under_the_newest_answer_only(qapp, chat):
    chat.brain = Brain(Answer(text="Blue Snail: Lv 2", entities=["monster/100101"]),
                       Answer(text="A potion", entities=["item/2000000"]), Answer(text="Done"))
    ask_and_wait(qapp, chat, "tell me about blue snails")
    first = chat._next_steps
    assert chip_texts(first) == [EN(k, name="Blue Snail") for k in ("fu_where", "fu_level", "fu_drops")]
    chat.set_tags(["item/2000000"])
    first.flow.itemAt(2).widget().click()                      # "What does Blue Snail drop?"
    assert wait(qapp, lambda: not chat.busy)
    qapp.processEvents()
    assert chat.brain.asked[-1] == (EN("fu_drops", name="Blue Snail"), ["monster/100101"])
    assert chat.focus_keys == ["item/2000000"]                 # the player's own tag is back
    from maplehelper.ui.overlay import _alive
    assert not _alive(first) or first.isHidden()
    assert chip_texts(chat._next_steps) == [EN("fu_who_drops", name="Red Potion"), EN("fu_buy", name="Red Potion")]
    ask_and_wait(qapp, chat, "thanks")
    assert chat._next_steps is None                            # no cards, no follow-ups


def test_a_follow_up_the_kb_answers_spends_no_ai(qapp, chat):
    """"Where is Red Snail?" under a card is answered from the KB (instant answers on), though the card is tagged."""
    from PySide6.QtWidgets import QLabel
    chat.settings["instant_answers"] = True
    chat.brain = Brain(Answer(text="A snail", entities=["monster/130101"]))
    ask_and_wait(qapp, chat, "tell me about it")
    chat._next_steps.flow.itemAt(0).widget().click()           # "Where is Red Snail?"
    qapp.processEvents()
    assert len(chat.brain.asked) == 1 and not chat.busy
    texts = [lb.text() for lb in chat.feed.findChildren(QLabel)]
    assert any("Henesys Hunting Ground I" in x for x in texts)
    chat._next_steps.flow.itemAt(1).widget().click()           # "Is Red Snail good for my level?": the AI's
    assert wait(qapp, lambda: not chat.busy)
    assert chat.brain.asked[-1] == (EN("fu_level", name="Red Snail"), ["monster/130101"])


def test_without_an_ai_the_chat_offers_what_works_without_one(qapp, chat):
    pages, sections = [], []
    chat.tools_page_requested.connect(pages.append)
    chat.settings_section_requested.connect(sections.append)
    chat.settings["no_ai"], chat.settings["instant_answers"] = True, True
    chat.clear_feed()
    chat.refresh_profile_chip()
    assert not chat.profile_card.now_btn.isVisibleTo(chat)     # "What now?" is the AI's
    # starters only the AI answers turn into their play-tools page
    shown = [chat.starters.flow.itemAt(i).widget().text() for i in range(chat.starters.count())]
    assert shown == [EN("open_in_tools", page=EN("tool_train")), EN("open_in_tools", page=EN("tool_quests"))]
    chat.starters.flow.itemAt(1).widget().click()
    assert pages == ["quests"]
    # an instant answer: no "Ask Claude anyway"; follow-ups only the KB answers
    ask_and_wait(qapp, chat, "Red Snail HP")
    assert EN.p("quick_ask_ai", "claude") not in chip_texts(chat.feed)
    assert chip_texts(chat._next_steps) == [EN("fu_where", name="Red Snail")]
    # a question for the AI: connect one, or the play tools page that fits
    chat.brain = Brain(Answer(error="no_ai"))
    ask_and_wait(qapp, chat, "where should I train at level 20?")
    assert chip_texts(chat._next_steps) == [EN("fix_connect_ai"), EN("open_in_tools", page=EN("tool_train"))]
    chat._next_steps.flow.itemAt(0).widget().click()
    assert sections == ["ai"]


def test_reading_the_profile_without_an_ai_says_how_to_connect_one(qapp, chat, monkeypatch):
    from maplehelper.ui import overlay as ov
    shots, done = [], []
    monkeypatch.setattr(chat, "_step_aside", lambda then: shots.append(then))
    chat.sync_finished.connect(done.append)
    chat.settings["no_ai"] = True
    chat.sync_profile()
    assert shots == [] and done == [False] and not getattr(chat, "_syncing", False)
    texts = [lb.text() for lb in chat.feed.findChildren(ov.SystemLine)]
    assert texts and EN("err_no_ai") in texts[-1] and chip_texts(chat._next_steps) == [EN("fix_connect_ai")]
    # with an AI, a failed read says what went wrong the same way (not "Something went wrong")
    chat.settings["no_ai"] = False
    chat._sync_cid = chat.profiles.active_id
    chat._on_sync_done(Answer(error="not_logged_in"))
    assert EN.p("err_not_logged_in", "claude") in [lb.text() for lb in chat.feed.findChildren(ov.SystemLine)][-1]
    assert chip_texts(chat._next_steps) == [EN("sign_in")] and done == [False, False]


def test_open_in_play_tools(qapp, chat):
    chat.brain = Brain(Answer(text="Go to Pig Beach"))
    pages = []
    chat.tools_page_requested.connect(pages.append)
    ask_and_wait(qapp, chat, "where should I train at level 20?")
    assert chip_texts(chat._next_steps) == [EN("open_in_tools", page=EN("tool_train"))]
    chat._next_steps.flow.itemAt(0).widget().click()
    assert pages == ["train"]


def test_the_thinking_line_says_what_the_ai_looks_up(qapp, chat):
    chat.brain = Brain(status="read:monster/100101")
    chat.brain.go.clear()                                      # the answer waits until the status is seen
    assert chat.ask("where are blue snails")
    assert wait(qapp, lambda: chat._pending_bubble._shown[0] == EN("status_read", name="Blue Snail"))
    chat.brain.go.set()
    assert wait(qapp, lambda: not chat.busy)
    assert chat._pending_bubble._shown[0] == "ok"
    chat._on_status("search")                                 # a late status never overwrites the answer
    assert chat._pending_bubble._shown[0] == "ok"


def test_the_screenshot_is_the_first_thing_it_looks_at(qapp, chat):
    chat.brain.go.clear()
    chat.shot, chat.shot_used, chat.game_hwnd = b"jpeg", False, 1
    assert chat.ask("what am I looking at")
    assert chat._pending_bubble._shown[0] == EN("status_shot")
    chat.brain.go.set()
    assert wait(qapp, lambda: not chat.busy)


def test_api_key_answers_show_their_cost_and_count_it(qapp, chat, data_dir):
    from PySide6.QtWidgets import QLabel
    chat.brain = Brain(Answer(text="Hi", cost_usd=0.0041), api_key="sk-test")
    ask_and_wait(qapp, chat, "hi")
    assert "$0.004" in [lb.text() for lb in chat._pending_bubble.findChildren(QLabel)]
    assert wait(qapp, lambda: costs.month_total() == pytest.approx(0.0041))
    chat.brain = Brain(Answer(text="Hi", cost_usd=0.0041))      # a subscription login: no cost line
    ask_and_wait(qapp, chat, "hi again")
    assert "$0.004" not in [lb.text() for lb in chat._pending_bubble.findChildren(QLabel)]


def test_rating_an_answer_saves_it_locally(qapp, chat, data_dir):
    from maplehelper.ui.chatbits import Rating
    chat.brain = Brain(Answer(text="Ellinia", entities=["monster/100101"], model="claude-sonnet-5"))
    ask_and_wait(qapp, chat, "where are blue snails")
    rating = chat._pending_bubble.findChild(Rating)
    rating.buttons["down"].click()
    assert wait(qapp, lambda: feedback.load())
    r = feedback.load()[0]
    assert (r["question"], r["answer"], r["rating"], r["entities"], r["model"], r["lang"]) == \
        ("where are blue snails", "Ellinia", "down", ["monster/100101"], "claude-sonnet-5", "en")
    assert rating.buttons["up"].isHidden() and not rating.buttons["down"].isEnabled()


def test_errors_come_with_their_fix(qapp, chat):
    sections, savers = [], []
    chat.settings_section_requested.connect(sections.append)
    chat.saver_requested.connect(lambda: savers.append(1))
    chat.brain = Brain(Answer(error="no_ai"), Answer(error="usage_limit"), Answer(error="timeout"), Answer(text="ok"))
    ask_and_wait(qapp, chat, "hi")
    assert chat._pending_bubble._shown[0] == EN("err_no_ai")
    assert chip_texts(chat._next_steps) == [EN("fix_connect_ai")]
    chat._next_steps.flow.itemAt(0).widget().click()
    assert sections == ["ai"]
    ask_and_wait(qapp, chat, "hi")
    chat._next_steps.flow.itemAt(0).widget().click()
    assert savers == [1]
    ask_and_wait(qapp, chat, "tell me")
    assert chip_texts(chat._next_steps) == [EN("retry")]
    bubbles = len(chat.brain.asked)
    chat._next_steps.flow.itemAt(0).widget().click()           # "Try again": the same question, asked again
    assert wait(qapp, lambda: not chat.busy and len(chat.brain.asked) == bubbles + 1)
    assert chat.brain.asked[-1][0] == "tell me" and chat._pending_bubble._shown[0] == "ok"


def test_no_game_window_explains_how_to_fix_it(qapp, chat):
    from PySide6.QtWidgets import QLabel

    from maplehelper.ui.widgets import NoticeCard
    chat.game_hwnd, chat.shot = None, None
    ask_and_wait(qapp, chat, "hi")
    card = chat.feed.findChildren(NoticeCard)[-1]
    card.btn.click()
    qapp.processEvents()
    assert any(lb.text() == EN("game_help") for lb in chat.feed.findChildren(QLabel))


def test_keyboard_shortcuts(qapp, chat, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    closed, searched = [], []
    monkeypatch.setattr(chat, "close_overlay", lambda: closed.append(1))
    chat.history_requested.connect(lambda: searched.append(1))
    ask_and_wait(qapp, chat, "where are blue snails")
    QTest.keyClick(chat.input, Qt.Key_Up)                     # ↑ in the empty field: the last question
    assert chat.input.text() == "where are blue snails"
    chat.input.setText("half typed")
    QTest.keyClick(chat.input, Qt.Key_Up)
    assert chat.input.text() == "half typed"                  # never over the player's own text
    QTest.keyClick(chat.input, Qt.Key_F, Qt.ControlModifier)
    assert searched == [1]
    QTest.keyClick(chat.input, Qt.Key_Escape)
    assert closed == [1]                                       # nothing running: Esc closes the chat
    chat.brain.go.clear()
    assert chat.ask("long one")
    QTest.keyClick(chat.input, Qt.Key_Escape)                  # mid-answer: Esc stops it, the chat stays
    assert closed == [1] and chat._stopping
    assert wait(qapp, lambda: not chat.busy)
    assert EN("keys_hint") == chat.input.toolTip()


def test_settings_show_the_month_and_save_the_window_prefs(qapp, isolated_store, kb, data_dir, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from maplehelper import providers
    from maplehelper.ui.dialogs import SettingsDialog
    monkeypatch.setattr(type(providers.get("claude")), "account", lambda self: {"status": "ok", "email": "a@b.c"})
    s = isolated_store.Settings()
    s["language"] = "en"
    costs.add(1.2345)
    month = EN("cost_month", usd="1.23")
    dlg = SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    assert month not in [lb.text() for lb in dlg.findChildren(QLabel)]          # a plan login: no cost
    s.set_api_key_mode("claude", True)
    dlg = SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")
    assert month in [lb.text() for lb in dlg.findChildren(QLabel)]
    dlg.resize(500, 400)
    dlg.show()
    dlg.show_section("ai")
    assert wait(qapp, lambda: dlg._scroll.verticalScrollBar().value() > 0)      # the AI account in view
    dlg.opacity.setValue(75)
    dlg.click_through.setChecked(True)
    dlg._save()
    assert (s["chat_opacity"], s["click_through"]) == (75, True)

    dlg = SettingsDialog(s, isolated_store.Profiles(), kb, lambda *_: "")    # opened with click-through on
    s["click_through"] = False                                               # then F9 turned it off
    dlg._save()
    assert s["click_through"] is False                                       # an untouched switch keeps that


def test_opacity_and_click_through(qapp, chat):
    from PySide6.QtCore import Qt
    chat.settings["chat_opacity"] = 70
    assert chat.full_opacity() == pytest.approx(0.7)
    chat.settings["chat_opacity"] = 10
    assert chat.full_opacity() == pytest.approx(0.6)          # never so faint it gets lost
    chat.settings["click_through"] = True
    chat.apply_window_prefs()
    assert chat.windowFlags() & Qt.WindowTransparentForInput
    chat.open_overlay(None, None)                              # F9: the chat opens clickable again
    assert not chat.settings["click_through"]
    assert not chat.windowFlags() & Qt.WindowTransparentForInput
    assert chat.isVisible()
