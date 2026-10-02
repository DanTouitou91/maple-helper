"""Information and progress: drop source badges, data freshness, the progress log and its pace, goals,
the active-quest tracker, wishlist price drops and the guides' key points."""
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from maplehelper import plan, progress, quests, updater, wishlist
from maplehelper.i18n import I18n
from maplehelper.kb import KnowledgeBase

SNAIL = """# Snail
Drops (MS Classic)
Community sourced
Items players have personally seen drop in-game.
Use
1
Red Potion
Potion
MSEA reference drops
Read-only · 2 items
Classic World appears to draw from the pre-Big-Bang MapleSEA drop tables.
Use
2
Red Potion
Potion
Blue Potion
Potion
Associated Quests
Map Locations ( 1 )
"""

QUEST = """# Estelle's Special Sauce

Estelle's Special Sauce
Henesys · Start: Estelle · Turn in: Mrs. Ming Ming · Mrs. Ming Ming's Second Worry
Pre-requisites
Level Lv. 15+
Requirements
Pig's Head x 10 Defeat Blue Snail x 3
Rewards
705 EXP 438 Mesos
Description
01 Deliver the sauce.
NPCs
Start Estelle Victoria Road › The Field South of Ellinia
Turn in Mrs. Ming Ming Victoria Road › Henesys
"""

EXP_PAGE = "Level | EXP to next\n1 | 100 | x\n2 | 200 | x\n3 | 400 | x\n"


def _page(kb_dir, key, name, props, body):
    cat, _, slug = key.partition("/")
    front = json.dumps({"name": name, "category": cat, "props": props}, indent=1)
    (kb_dir / "pages" / cat).mkdir(parents=True, exist_ok=True)
    (kb_dir / "pages" / cat / f"{slug}.md").write_text(f"---\n{front}\n---\n\n{body}", encoding="utf-8")
    index = json.loads((kb_dir / "index.json").read_text(encoding="utf-8"))
    index = [e for e in index if e["key"] != key] + [{"key": key, "name": name, "category": cat, "props": props}]
    (kb_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


@pytest.fixture
def drop_kb(kb_copy):
    _page(kb_copy, "item/2000001", "Blue Potion", {}, "# Blue Potion\n")
    _page(kb_copy, "item/4000000", "Pig's Head", {}, "# Pig's Head\n")
    _page(kb_copy, "monster/100100", "Snail", {"Level": 1, "HP": 8, "EXP": 3}, SNAIL)
    _page(kb_copy, "quest/2000", "Estelle's Special Sauce", {"Minimum Level": 15, "EXP Reward": 705,
                                                              "NPC": "Estelle", "Area": "Henesys"}, QUEST)
    _page(kb_copy, plan.EXP_GUIDE, "EXP Table", {}, "".join(f"{lv} | {lv * 1000:,} | x\n" for lv in range(1, 31)))
    return kb_copy


EXP_KB = SimpleNamespace(page=lambda key: EXP_PAGE if key == plan.EXP_GUIDE else "")


# ---------------------------------------------------------------- drop source badges

def test_drops_above_the_msea_list_are_confirmed_in_classic(drop_kb):
    kb = KnowledgeBase(drop_kb)
    assert kb.drop_sources("monster/100100") == {"item/2000000": "classic", "item/2000001": "msea"}
    assert kb.monster_drops("monster/100100") == ["item/2000000", "item/2000001"]
    assert kb.drop_source("monster/100100", "item/2000001") == "msea"
    assert kb.drop_source("monster/100101", "item/2000000") is None
    digest = kb.drops_digest("monster/100100")
    assert "Red Potion [item/2000000] (confirmed in Classic)" in digest and "Blue Potion [item/2000001]," not in digest


def test_a_page_without_the_msea_heading_is_all_classic(kb_copy):
    _page(kb_copy, "monster/100100", "Snail", {"Level": 1}, "# Snail\nDrops (MS Classic)\nRed Potion\nMap Locations\n")
    assert KnowledgeBase(kb_copy).drop_sources("monster/100100") == {"item/2000000": "classic"}


def test_drop_table_carries_the_source_and_old_tables_still_load(drop_kb):
    import kb_release
    KnowledgeBase(drop_kb).ensure_drop_table()
    rows = (drop_kb / "drops.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0].endswith("\titem_key\tsource")
    assert {r.split("\t")[-1] for r in rows[1:]} == {"classic", "msea"}
    assert kb_release._drops(drop_kb)["monster/100100"]["item/2000001"] == ("Blue Potion", "msea")
    (drop_kb / "drops.tsv").write_text("monster\tmonster_level\tmonster_key\titem\titem_type\titem_key\n"
                                       "Snail\t1\tmonster/100100\tRed Potion\tUse\titem/2000000\n", encoding="utf-8")
    assert kb_release._drops(drop_kb) == {"monster/100100": {"item/2000000": ("Red Potion", "")}}


def test_a_drop_confirmed_in_classic_reaches_the_patch_notes(drop_kb, tmp_path):
    import shutil
    import kb_release
    old = tmp_path / "old"
    shutil.copytree(drop_kb, old)
    page = drop_kb / "pages" / "monster" / "100100.md"
    page.write_text(page.read_text(encoding="utf-8").replace("Red Potion\nPotion\nMSEA", "Red Potion\nPotion\nBlue Potion\nMSEA"),
                    encoding="utf-8")
    entry = kb_release.record_changes(drop_kb, old, "2026.10.03.0100")
    c = entry["changed"][0]
    assert c["key"] == "monster/100100" and c["drops_confirmed"] == ["Blue Potion"] and "drops_added" not in c
    assert wishlist.touched([entry], ["item/2000001"], KnowledgeBase(drop_kb)) == ["Blue Potion"]


def test_drop_tiles_show_their_badge(drop_kb, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from maplehelper.ui import terms
    from maplehelper.ui.widgets import DropGroupCard
    monkeypatch.setattr(terms, "LANG", "en")
    kb = KnowledgeBase(drop_kb)
    card = DropGroupCard(kb, "monster/100100", ["item/2000000", "item/2000001"])
    tags = {lb.text(): lb.objectName() for lb in card.findChildren(QLabel) if lb.objectName() in ("TagGood", "Tag")}
    assert tags == {"✓ Classic": "TagGood", "MSEA ref": "Tag"}


# ---------------------------------------------------------------- data freshness

def test_data_date_from_fetched_at_or_the_version(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"fetched_at": "2026-10-02T06:38:53Z", "version": "x"}))
    assert updater.data_time(tmp_path) == datetime(2026, 10, 2, 6, 38, 53, tzinfo=timezone.utc).timestamp()
    (tmp_path / "meta.json").write_text(json.dumps({"version": "2026.10.02.0638"}))
    assert updater.data_time(tmp_path) == datetime(2026, 10, 2, 6, 38, tzinfo=timezone.utc).timestamp()
    (tmp_path / "meta.json").write_text("{broken")
    assert updater.data_time(tmp_path) is None and updater.freshness(I18n("en"), tmp_path) == ""


@pytest.mark.parametrize("hours,en,he", [(0.5, "less than an hour ago", "לפני פחות משעה"), (1, "an hour ago", "לפני שעה"),
                                         (5, "5 hours ago", "לפני 5 שעות"), (30, "yesterday", "אתמול"),
                                         (72, "3 days ago", "לפני 3 ימים"), (24 * 90, "3 months ago", "לפני 3 חודשים"),
                                         (24 * 400, "over a year ago", "לפני יותר משנה")])
def test_freshness_reads_naturally(tmp_path, hours, en, he):
    (tmp_path / "meta.json").write_text(json.dumps({"version": "2026.10.02.0000"}))
    now = updater.data_time(tmp_path) + hours * 3600
    assert updater.freshness(I18n("en"), tmp_path, now) == f"Game data updated {en}"
    assert updater.freshness(I18n("he"), tmp_path, now) == f"נתוני המשחק עודכנו {he}"


# ---------------------------------------------------------------- progress log, pace and forecast

def test_level_and_exp_changes_are_logged_from_every_path(isolated_store):
    p = isolated_store.Profiles()
    c = p.add("Kiwi", "Warrior", "Warrior", 30)
    log = isolated_store.ProgressLog(c.id)
    assert [s[1:] for s in log.samples()] == [[30, None]]
    p.apply_update({"exp_percent": 40})
    p.apply_update({"exp_percent": 40, "note": "x"})              # nothing new: no point
    p.apply_update({"level": 31, "exp_percent": 2})
    p.apply_update({"level": 32})                                   # a level without a reading
    p.apply_update({"map": "Perion"})
    p.edit(c.id, "Kiwi", "Warrior", "Fighter", 33)
    assert [s[1:] for s in log.samples()] == [[30, None], [30, 40.0], [31, 2.0], [32, None], [33, None]]
    p.remove(c.id)
    assert log.samples() == []


def test_exp_per_hour_leaves_out_the_breaks():
    samples = [[0, 1, 0.0], [1800, 1, 50.0], [3600, 2, 0.0],      # 100 EXP in an hour of play
               [3600 + 5 * 3600, 2, 50.0],                         # a night in between: not play
               [3600 + 5 * 3600 + 900, 2, 75.0], [3600 + 5 * 3600 + 1000, 3, None]]
    # 100 EXP + 50 EXP over 1.25 h
    assert progress.exp_per_hour(EXP_KB, samples) == pytest.approx(120)
    assert progress.exp_per_hour(EXP_KB, samples[:1]) is None
    assert progress.exp_per_hour(EXP_KB, [[0, 1, 0.0], [60, 1, 1.0]]) is None          # a minute says nothing
    assert progress.points([[60, 2, None], [0, 1, 50.0]]) == [(0, 1.5), (60, 2.0)]


def test_forecast_to_the_next_level_and_a_goal():
    assert progress.exp_to(EXP_KB, 1, 50, 2) == 50
    assert progress.exp_to(EXP_KB, 1, 50, 3) == 250
    assert progress.exp_to(EXP_KB, 2, 0, 9) is None                                    # past the EXP table
    assert progress.hours_to(EXP_KB, 1, 50, 3, 100) == 2.5
    assert progress.hours_to(EXP_KB, 1, 50, 3, None) is None
    t = I18n("en")
    assert [progress.duration(t, h) for h in (0.5, 1, 2.54, 12.4)] == ["30 min", "1 h", "2.5 h", "12 h"]
    assert progress.duration(I18n("he"), 2.5) == "2.5 שע'"


# ---------------------------------------------------------------- goals

def test_level_goals_persist_and_complete_themselves(isolated_store):
    p = isolated_store.Profiles()
    p.add("Kiwi", "Warrior", "Warrior", 30)
    p.add_goal(35)
    p.add_goal(35)                                     # once
    p.add_goal(20)                                     # already there
    goals = {g["level"]: g for g in isolated_store.Profiles().active.goals}
    assert set(goals) == {35, 20} and not goals[35]["done"] and goals[20]["done"]
    p.apply_update({"level": 35})
    assert all(g["done"] for g in isolated_store.Profiles().active.goals)
    p.remove_goal(20)
    assert [g["level"] for g in isolated_store.Profiles().active.goals] == [35]


# ---------------------------------------------------------------- active quests

def test_quest_tracker_ticks_and_completes(isolated_store):
    p = isolated_store.Profiles()
    p.add("Kiwi", "Warrior", "Warrior", 30)
    p.track_quest("Estelle's Special Sauce")
    p.track_quest("Estelle's Special Sauce")
    p.tick_quest("Estelle's Special Sauce", "Pig's Head x 10", True)
    c = isolated_store.Profiles().active
    assert c.active_quests == ["Estelle's Special Sauce"] and c.quest_ticks == {"Estelle's Special Sauce": ["Pig's Head x 10"]}
    p.tick_quest("Estelle's Special Sauce", "Pig's Head x 10", False)
    assert isolated_store.Profiles().active.quest_ticks["Estelle's Special Sauce"] == []
    p.complete_quest("Estelle's Special Sauce", "quest/2000")
    c = isolated_store.Profiles().active
    assert c.active_quests == [] and c.quest_ticks == {} and c.quests_done == ["quest/2000"]
    p.track_quest("Q")
    p.tick_quest("Q", "A x 1", True)
    p.apply_update({"quests_completed": ["Q"]})                    # the chat completes it: the ticks go too
    assert isolated_store.Profiles().active.quest_ticks == {}


def test_a_quest_the_chat_completes_is_done_on_the_quests_page(isolated_store):
    """The AI's "quests_completed" names land in quests_done as KB keys, and leave the tracker."""
    keys = {"estelle's special sauce": "quest/2000"}
    p = isolated_store.Profiles()
    p.add("Kiwi", "Warrior", "Warrior", 30)
    p.track_quest("Estelle's Special Sauce")
    changes = p.apply_update({"quests_completed": ["estelle's special sauce", "Untracked one"]},
                             quest_key=lambda name: keys.get(name.lower()))
    c = isolated_store.Profiles().active
    assert c.active_quests == [] and c.quests_done == ["quest/2000"]
    assert changes == [("quest-", "estelle's special sauce")]       # the unknown, untracked one changes nothing
    assert p.apply_update({"quests_completed": ["Estelle's Special Sauce"]}, quest_key=lambda n: "quest/2000") == []


def test_quest_requirements_and_where_to_turn_in(drop_kb):
    kb = KnowledgeBase(drop_kb)
    q = quests.by_name(kb, "estelle's special sauce")
    assert q.key == "quest/2000" and q.needs == ["Pig's Head x 10", "Defeat Blue Snail x 3"]
    assert quests.by_name(kb, "quest/2000") is q and quests.by_name(kb, "Nope") is None
    assert quests.turn_in(kb, "quest/2000") == ("Mrs. Ming Ming", "Henesys")
    assert quests.turn_in(kb, "quest/1000") == ("", "")
    assert quests.need_parts("Defeat Blue Snail x 3") == ("monster", "Blue Snail", 3)
    assert quests.need_parts("Pig's Head x 1,000") == ("item", "Pig's Head", 1000)
    assert quests.need_parts("Talk to Mai") == ("", "Talk to Mai", 0)


# ---------------------------------------------------------------- wishlist price drops

def test_price_drops_are_announced_once(isolated_store):
    s = isolated_store.Settings()
    seen = [wishlist.price_seen(s, "item/1", m) for m in (1000, 950, 800, 790, None)]
    assert [news for _, news in seen] == [False, False, True, False, False]
    assert seen[2][0]["was"] == 950 and seen[3][0]["was"] == 950            # still down since that drop
    assert isolated_store.Settings()["wish_prices"]["item/1"]["median"] == 790
    rec, news = wishlist.price_seen(s, "item/1", 1000)
    assert "was" not in rec and not news                                    # back up: the heads-up is over
    assert wishlist.price_seen(s, "item/1", 700)[1]


# ---------------------------------------------------------------- guide key points

def test_every_guide_has_three_key_points_in_both_languages():
    from maplehelper import guides
    import re
    hebrew = re.compile(r"[֐-׿]")
    files = sorted((guides.TRANSLATIONS / "en").glob("*.json"))
    assert files
    for f in files:
        en = json.loads(f.read_text(encoding="utf-8"))
        he = json.loads((guides.TRANSLATIONS / "he" / f.name).read_text(encoding="utf-8"))
        for lang, g in (("en", en), ("he", he)):
            assert len(g.get("tldr", [])) == 3 and all(x.strip() for x in g["tldr"]), (f.stem, lang)
        assert not any(hebrew.search(x) for x in en["tldr"]) and all(hebrew.search(x) for x in he["tldr"]), f.stem
        assert guides.book("guide/" + f.stem, "he")["tldr"] == he["tldr"]
    b = guides.book("guide/" + files[0].stem, "en")
    assert "In short" in guides.book_html(b, tldr_head="In short") and "In short" not in guides.book_html(b)


def test_guide_tools_keep_the_key_points(tmp_path, monkeypatch):
    import build_guides as bg
    import translate_guides as tg
    en = {"title": "Guide", "intro": "Hi.", "blocks": [{"p": "Hit **hard**."}], "source": "x"}
    en["hash"] = bg.content_hash(en)
    old = tmp_path / "old.json"
    old.write_text(json.dumps({**en, "tldr": ["a", "b", "c"]}), encoding="utf-8")
    kept = bg.keep_tldr(en, old)
    assert list(kept)[:3] == ["title", "intro", "tldr"] and kept["tldr"] == ["a", "b", "c"]
    assert bg.content_hash(kept) == en["hash"]                     # never marks a translation outdated
    assert bg.keep_tldr(en, tmp_path / "missing.json") is en
    # a re-imported translation keeps its key points unless they were translated too
    root = tmp_path / "guides"
    for lang, data in (("en", {**en, "tldr": ["a", "b", "c"]}), ("he", {"title": "מדריך", "tldr": ["א", "ב", "ג"]})):
        (root / lang).mkdir(parents=True)
        (root / lang / "g.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tg, "GUIDES", root)
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "g.json").write_text(json.dumps({"0": "מדריך"}, ensure_ascii=False), encoding="utf-8")
    tg.import_("he", inbox)
    he = json.loads((root / "he" / "g.json").read_text(encoding="utf-8"))
    assert he["tldr"] == ["א", "ב", "ג"] and he["source_hash"] == en["hash"]
    src = {str(i): s for i, s in enumerate(dict.fromkeys(tg.strings({**en, "tldr": ["a", "b", "c"]})))}
    assert {"a", "b", "c"} <= set(src.values())
    (inbox / "g.json").write_text(json.dumps({i: s.upper() for i, s in src.items()}), encoding="utf-8")
    tg.import_("he", inbox)
    assert json.loads((root / "he" / "g.json").read_text(encoding="utf-8"))["tldr"] == ["A", "B", "C"]


# ---------------------------------------------------------------- the windows (offscreen Qt)

@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def settle(app, ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_progress_page_empty_state_then_chart_and_goals(qt_app, isolated_store, drop_kb):
    from maplehelper.ui.tools import PAGES, ToolsDialog
    kb = KnowledgeBase(drop_kb)
    profiles, settings = isolated_store.Profiles(), isolated_store.Settings()
    c = profiles.add("Kiwi", "Warrior", "Warrior", 12)
    d = ToolsDialog(kb, profiles, settings, "en", "", {}, "progress")
    assert d.stack.currentWidget() is d.pages["progress"]
    assert d.prog_chart.isHidden() and not d.prog_empty.isHidden()
    assert "Not enough readings" in d.prog_forecast.text()
    profiles.apply_update({"exp_percent": 10})
    profiles.add_goal(15)
    wishlist.toggle(settings, c.id, "item/2000001")
    d.meter[c.id] = {"result": {"per_hour": 5000, "minutes": 20}}
    d.refresh()
    assert not d.prog_chart.isHidden() and len(d.prog_chart.points) == 2
    assert d.prog_cells["per_hour"][0].text() == "5,000" and "EXP meter" in d.prog_forecast.text()
    assert d.goal_list.count() == 2                                     # the level goal and the wished item
    d.goal_item.setText("Pig's Head")
    d._add_item_goal()
    assert wishlist.items(settings, c.id) == ["item/2000001", "item/4000000"]
    d.show_page(PAGES.index("quests"))
    d.close()


def test_my_quests_list_the_tracked_ones(qt_app, isolated_store, drop_kb):
    from PySide6.QtWidgets import QPushButton
    from maplehelper.ui.tools import ToolsDialog
    kb = KnowledgeBase(drop_kb)
    profiles = isolated_store.Profiles()
    profiles.add("Kiwi", "Warrior", "Warrior", 16)
    profiles.track_quest("Estelle's Special Sauce")
    profiles.track_quest("Unknown quest")
    d = ToolsDialog(kb, profiles, isolated_store.Settings(), "en", "", {}, "quests")
    next(b for b in d.q_mode.findChildren(QPushButton) if b.property("value") == "mine").click()
    assert d.q_list.count() == 2 and "2 active quests" in d.q_head.text()
    boxes = [b for b in d.pages["quests"].findChildren(QPushButton) if b.objectName() == "SubChip"]
    assert len(boxes) == 2
    boxes[0].click()
    assert profiles.active.quest_ticks == {"Estelle's Special Sauce": ["Pig's Head x 10"]}
    d.close()


def test_wishlist_window_shows_a_price_drop_once(qt_app, isolated_store, drop_kb, monkeypatch):
    from maplehelper import market
    from maplehelper.ui import wishlist as window
    kb = KnowledgeBase(drop_kb)
    settings = isolated_store.Settings()
    settings["wish_prices"] = {"item/2000001": {"median": 1000, "t": 0}}
    calls = []
    monkeypatch.setattr(market, "free_market", lambda name: calls.append(name) or market.Market(4, 700, 600, 900))
    monkeypatch.setattr(window, "_CHECKED", set())
    toasts = []
    d = window.WishlistDialog(["item/2000001"], kb, "en", "", settings)
    d.price_dropped.connect(lambda title, body: toasts.append(body))
    settle(qt_app, 300)
    assert calls == ["Blue Potion"] and toasts == ["Blue Potion: 700 mesos (was 1,000)"]
    assert d.prices["item/2000001"].objectName() == "TagGood" and "was 1,000" in d.prices["item/2000001"].text()
    window.WishlistDialog(["item/2000001"], kb, "en", "", settings)        # once per app session
    settle(qt_app, 100)
    assert calls == ["Blue Potion"]
    d.check_prices(force=True)                                           # "Check prices": again, no second toast
    settle(qt_app, 300)
    assert calls == ["Blue Potion"] * 2 and len(toasts) == 1




def test_badges_show_once_anything_is_confirmed(drop_kb):
    kb = KnowledgeBase(drop_kb)
    assert kb.confirms_drops and kb.badge_source("monster/100100", "item/2000001") == "msea"



def test_no_badges_while_nothing_is_confirmed(drop_kb):
    # the live database's "Drops (MS Classic)" lists are empty: "MSEA ref" on every drop would tell nothing
    unconfirmed = SNAIL.replace("Use\n1\nRed Potion\nPotion\n", "", 1)
    assert unconfirmed != SNAIL
    _page(drop_kb, "monster/100100", "Snail", {"Level": 1, "HP": 8, "EXP": 3}, unconfirmed)
    kb = KnowledgeBase(drop_kb)
    pairs = [(m, i) for i, ms in kb.droppers.items() for m in ms]
    assert pairs and not kb.confirms_drops
    assert all(kb.drop_source(m, i) == "msea" and kb.badge_source(m, i) is None for m, i in pairs)


def _contrast(a: str, b: str = "#FFFFFF") -> float:
    def lum(c):
        lin = [v / 255 / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4
               for v in (int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_colors_drawn_in_code_follow_high_contrast(qt_app, isolated_store, drop_kb, monkeypatch):
    """Links, the "✓ Classic" note, the guides' links and the progress chart read at 4.5:1 or more on white."""
    import re

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QRegion
    from PySide6.QtWidgets import QWidget

    from maplehelper import guides
    from maplehelper.ui import theme
    from maplehelper.ui.tools import LevelChart, ToolsDialog
    monkeypatch.setattr(theme, "MODE", "contrast")
    profiles = isolated_store.Profiles()
    profiles.add("Kiwi", "Warrior", "Warrior", 16)
    d = ToolsDialog(KnowledgeBase(drop_kb), profiles, isolated_store.Settings(), "en", "", {}, "quests")
    hint = d._need_hint("Red Potion x 3")
    d.close()
    colors = re.findall(r"color: (#[0-9A-Fa-f]{6})", hint)
    assert "Classic" in hint and len(colors) == 2
    assert all(_contrast(c) >= 4.5 for c in colors), colors

    page = guides.book_html({"lang": "en", "blocks": [{"guide": "guide/x", "text": "More"}]}, "contrast")
    link = re.search(r"color: (#[0-9A-Fa-f]{6})", page)[1]
    assert _contrast(link) >= 4.5 and _contrast(link, guides.NOTE_COLORS["contrast"]["note"]) >= 4.5

    chart = LevelChart()
    chart.resize(300, 170)
    chart.set_points([(0, 10.0), (3600, 10.5), (7200, 11.2)])
    img = QImage(chart.size(), QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    chart.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)        # on white, as the page shows it
    seen = {QColor(img.pixel(x, y)).name() for x in range(300) for y in range(170)}
    accent, grid = theme.P()["accent"], theme.P()["grid"]
    assert accent.lower() in seen and theme.ORANGE.lower() not in seen
    assert _contrast(accent) >= 4.5 and _contrast(grid) < _contrast(accent)     # the line is the strongest thing
