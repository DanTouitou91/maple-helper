"""The play-tools window: pages build when first opened, held steppers save once (offscreen Qt)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def tools(isolated_store, kb):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from maplehelper.ui.tools import ToolsDialog
    profiles = isolated_store.Profiles()
    profiles.add("Kiwi", "Thief", "Assassin", 12)
    saves = []
    real = profiles.save
    profiles.save = lambda: (saves.append(1), real())
    d = ToolsDialog(kb, profiles, isolated_store.Settings(), "en", "", {})
    yield app, d, profiles, saves
    d.close()


@pytest.fixture
def drop_kb_tools(isolated_store, kb_copy):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from test_info_progress import QUEST, _page

    from maplehelper.kb import KnowledgeBase
    _page(kb_copy, "quest/2000", "Estelle's Special Sauce", {"Minimum Level": 15, "EXP Reward": 705,
                                                              "NPC": "Estelle", "Area": "Henesys"}, QUEST)
    profiles = isolated_store.Profiles()
    profiles.add("Kiwi", "Warrior", "Warrior", 16)
    return KnowledgeBase(kb_copy), profiles


def settle(app, ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_pages_are_built_when_first_opened(tools):
    from maplehelper.ui.tools import PAGES
    app, d, _, _ = tools
    assert list(d.pages) == ["train"]
    d.show_page(PAGES.index("exp"))
    assert set(d.pages) == {"train", "exp"} and d.stack.currentWidget() is d.pages["exp"]
    d.show_page(PAGES.index("train"))
    assert d.stack.currentWidget() is d.pages["train"]


def test_a_held_stepper_saves_once(tools):
    app, d, profiles, saves = tools
    st = d._steppers[0]["acc"]
    for _ in range(10):
        st.setValue(st.value() + 1)
    assert saves == [] and profiles.active.stats["acc"] == 10
    settle(app, 400)
    assert saves == [1]


def test_closing_right_after_a_change_still_saves(tools):
    app, d, profiles, saves = tools
    d.show()
    d._steppers[0]["acc"].setValue(42)
    d.close()
    assert saves == [1]


def test_picker_rows_are_built_once_per_kb(kb):
    from maplehelper.ui.tools import monster_rows
    assert monster_rows(kb) is monster_rows(kb)


def test_a_failed_read_ends_the_exp_meter_wait(tools):
    from maplehelper.ui.tools import PAGES
    app, d, profiles, _ = tools
    d.show_page(PAGES.index("exp"))
    d.meter["pending"] = ("start", profiles.active.id)
    d.sync_done(False)
    assert "pending" not in d.meter
    assert "read the game. Make sure" in d.exp_status.text()       # not overwritten by the redraw's idle steps


def test_without_an_ai_the_screen_reading_buttons_step_aside(tools):
    from maplehelper.ui.tools import PAGES
    app, d, profiles, _ = tools
    d.settings["no_ai"] = True
    for name in ("exp", "progress", "calc"):
        d.show_page(PAGES.index(name))
    assert d.exp_start.isHidden() and d.exp_measure.isHidden() and "takes an AI" in d.exp_status.text()
    assert "with an AI connected" in d.prog_forecast.text()
    reads = [b for b in d.findChildren(type(d.exp_start)) if b.text() == d._p(d.t("my_stats_read"))]
    assert reads and all(b.isHidden() for b in reads)
    d.settings["no_ai"] = False                                  # connected meanwhile: the meter is back
    d.show_page(PAGES.index("exp"))
    assert not d.exp_start.isHidden() and "takes an AI" not in d.exp_status.text()


def test_marking_a_quest_done_takes_it_off_my_quests(isolated_store, drop_kb_tools):
    from maplehelper.ui.tools import ToolsDialog
    kb, profiles = drop_kb_tools
    profiles.track_quest("Estelle's Special Sauce")
    profiles.tick_quest("Estelle's Special Sauce", "Pig's Head x 10", True)
    d = ToolsDialog(kb, profiles, isolated_store.Settings(), "en", "", {}, "quests")
    d._quest_done("quest/2000")
    c = profiles.active
    assert c.quests_done == ["quest/2000"] and c.active_quests == [] and c.quest_ticks == {}
    d.close()


def test_history_search_waits_for_the_typing_to_pause(tools):
    app = tools[0]
    from maplehelper.ui.pinsview import HistoryDialog
    pairs = [{"q": f"question {i}", "a": f"answer {i}", "t": 0} for i in range(5)]
    d = HistoryDialog(pairs, "Kiwi", "en", "")
    fills = []
    real = d._fill
    d._search_soon.timeout.disconnect()
    d._search_soon.timeout.connect(lambda: (fills.append(1), real()))
    for ch in "answer 3":
        d.search.insert(ch)
    assert fills == []
    settle(app, 300)
    assert fills == [1] and "1" in d.count.text()
