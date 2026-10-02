"""The play tools' calculations on small pages written here (CI has no real knowledge base):
combat math and monster pages, quest pages, crafting tables, the job tree and the build plan."""
import gc
import json
import weakref
from types import SimpleNamespace

import pytest

from maplehelper import buildplan, combat, crafting, plan, quests
from maplehelper.kb import KnowledgeBase

MONSTER = """# Axe Stump
HP
371
P.DEF
30
M.DEF
—
AVOID
8
Map Locations ( 4 )
Map | Count ↓ | Share ↓ | Types ↓ | Mob Rate | Respawn
Warrior's Rocky Mountain Victoria Road | 30 | 30 / 30 100 % | 1 | 1.0 x | ~7.5s
Orbis Tower Ossyria | 25 | 25 / 25 100 % | 1 | 1.0 x | ~7.5s
Dangerous Valley II Victoria Road | 21 | 21 / 40 52 % | 3 | 1.0 x | ~7.5s
Burnt Land I Victoria Road | 12 | 12 / 30 40 % | 3 | 1.0 x | ~7.5s
Change history
HP | 7,560 | 371
"""

QUEST = """# Winston's Fossil Hunt

Pre-requisites
Level Lv. 30+
Job Warrior only
Quest Complete Mai's Training
Requirements
Defeat Axe Stump x 25 Fox Tail x 10 Wax x 5
Rewards
1,200 EXP 3,000 Mesos
Mana Elixir x 2 Lemon x 10 Elixir x 15
Description
01 Bring the fossils to Winston.
"""

SMITHING = """# Smithing Efficiency

Lv. 1
needs 50 EXP · char Lv. 10 + ( 2 recipes )
# | Recipe / Ingredients | EXP | Catalyst | Mat value | Mat Craft Value | Sell-back | Net | EXP / meso | Mats
1 | Bronze Ingot
5 x Bronze Ore
| 3 | 100 | + 100 | - | + 100 | -100 | 0.030 | Farm only
2 | Metal Koif
1 x Bronze Koif 2 x Iron Ingot
| 20 | 1,000 | + 800 | + 200 | + 650 | -1,150 | 0.017 | Mixed
Lv. 2
needs 115 EXP · char Lv. 10 + ( 0 recipes )
"""


def _page(kb_dir, key, name, props, body):
    cat, _, slug = key.partition("/")
    front = json.dumps({"name": name, "category": cat, "props": props}, indent=1)
    (kb_dir / "pages" / cat).mkdir(parents=True, exist_ok=True)
    (kb_dir / "pages" / cat / f"{slug}.md").write_text(f"---\n{front}\n---\n\n{body}", encoding="utf-8")
    index = json.loads((kb_dir / "index.json").read_text(encoding="utf-8"))
    index = [e for e in index if e["key"] != key] + [{"key": key, "name": name, "category": cat, "props": props}]
    (kb_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


@pytest.fixture
def play_kb(kb_copy):
    _page(kb_copy, "monster/5130104", "Axe Stump", {"Level": 17, "HP": 371, "EXP": 32}, MONSTER)
    _page(kb_copy, "quest/2000", "Winston's Fossil Hunt",
          {"Minimum Level": 30, "EXP Reward": 1200, "Meso Reward": 3000, "NPC": "Winston", "Area": "Perion"}, QUEST)
    _page(kb_copy, "crafting/efficiency__smithing", "Smithing Efficiency", {}, SMITHING)
    return kb_copy


# ------------------------------------------------------------------ combat math

def test_hit_chance_inside_the_random_range():
    # same level, 51 ACC -> A = 20 = the avoid: D = 0, f = 0.25, q = 1 -> (1 + f - q) / 2f = 0.5
    assert combat.hit_chance(51, 10, 10, 20) == pytest.approx(0.5)
    assert 0 < combat.hit_chance(45, 10, 10, 20) < 0.5 < combat.hit_chance(56, 10, 10, 20) < 1
    assert combat.hit_chance(10, 10, 10, 20) == 0.0 and combat.hit_chance(5, 10, 10, 0) == 1.0


def test_level_scale_switches_to_linear_at_a_gap_of_10():
    assert combat.level_scale(20, 29) == pytest.approx(1 / (1 + 81 * 0.005))
    assert combat.level_scale(20, 30) == pytest.approx(1 / 1.5)
    assert combat.level_scale(20, 40) == pytest.approx(1 / 2)


def test_landed_damage_is_truncated_and_clamped_like_the_game():
    # the guide's last step: trunc(clamp(value, 1, 99,999)); 13 raw on DEF 10 = 11.8 -> 11
    assert combat.landed(13, 10, 10, 10) == 11
    assert combat.landed(0.4, 0, 10, 10) == 1 and combat.landed(10 ** 6, 0, 10, 10) == 99999
    m = combat.Monster("monster/1", "Test", level=10, hp=106, exp=5, pdef=10)
    assert combat.hits_to_kill(13, 13, m, 10)[0] == 10        # 11.8 a hit said 9


def test_kills_to_level_from_the_exp_table():
    kb = SimpleNamespace(page=lambda k: "Level | EXP to next | Cumulative\n34 | 155,540 | 1 |\n"
                         if k == plan.EXP_GUIDE else "")
    m = combat.Monster("monster/9", "Jr. Wraith", level=34, hp=500, exp=70)
    assert combat.kills_to_level(kb, 34, 50.0, m) == 1111
    assert combat.kills_to_level(kb, 34, None, m) == 2222
    assert combat.kills_to_level(kb, 35, 0.0, m) is None


def test_monster_page_numbers_and_grind_maps(play_kb):
    m = combat.monster(KnowledgeBase(play_kb), "monster/5130104")
    assert (m.level, m.hp, m.exp, m.avoid, m.pdef, m.mdef) == (17, 371, 32, 8, 30, 0)
    # job-test and not-yet-released maps are left out; the change-history table below is not a map
    assert m.maps == [("Dangerous Valley II Victoria Road", 21), ("Burnt Land I Victoria Road", 12)]


def test_a_reloaded_kb_reads_fresh_numbers_and_frees_the_old_one(play_kb):
    old = KnowledgeBase(play_kb)
    assert combat.monster(old, "monster/5130104").hp == 371 and quests.quest(old, "quest/2000")
    _page(play_kb, "monster/5130104", "Axe Stump", {"Level": 17, "HP": 400, "EXP": 32}, MONSTER)
    new = KnowledgeBase(play_kb)
    assert combat.monster(new, "monster/5130104").hp == 400
    gone = weakref.ref(old)
    del old
    gc.collect()
    assert gone() is None


# ------------------------------------------------------------------ quests

@pytest.mark.parametrize("line,items", [
    ("Defeat Axe Stump x 20", ["Defeat Axe Stump x 20"]),
    ("Fox Tail x 10 Wax x 5", ["Fox Tail x 10", "Wax x 5"]),
    ("Defeat Blue Snail x 10 Defeat Shroom x 10 Defeat Red Snail x 5",
     ["Defeat Blue Snail x 10", "Defeat Shroom x 10", "Defeat Red Snail x 5"]),
    ("Mana Elixir x 2 Lemon x 10 Elixir x 1,500", ["Mana Elixir x 2", "Lemon x 10", "Elixir x 1,500"]),
    ("Star Pixie's Starpiece x 100", ["Star Pixie's Starpiece x 100"]),
])
def test_quest_items_with_an_x_in_the_name(line, items):
    assert [f"{n.strip()} x {c}" for n, c in quests._ITEM.findall(line)] == items


def test_quest_page(play_kb):
    q = quests.quest(KnowledgeBase(play_kb), "quest/2000")
    assert (q.level, q.job, q.after, q.exp, q.mesos) == (30, "Warrior only", "Mai's Training", 1200, 3000)
    assert q.needs == ["Defeat Axe Stump x 25", "Fox Tail x 10", "Wax x 5"]
    assert q.rewards == ["Mana Elixir x 2", "Lemon x 10", "Elixir x 15"]


@pytest.mark.parametrize("quest_job,base,job,fits", [
    ("", "Warrior", "Fighter", True),
    ("Beginner only", "Warrior", "Beginner", True),       # planned Warrior, still a Beginner
    ("Warrior only", "Warrior", "Beginner", False),
    ("Beginner only", "Beginner", "Beginner", True),
    ("Beginner only", "Warrior", "Warrior", False),
    ("Warrior only", "Warrior", "Fighter", True),
    ("Thief only", "Warrior", "Fighter", False),
])
def test_job_fits(quest_job, base, job, fits):
    assert quests.job_fits(quests.Quest("quest/1", "Q", 5, job=quest_job), base, job) is fits


def test_a_beginner_sees_beginner_quests_whatever_the_class_planned(play_kb):
    _page(play_kb, "quest/2001", "Mai's Training", {"Minimum Level": 3, "EXP Reward": 70},
          "Pre-requisites\nJob Beginner only\nRequirements\nDefeat Blue Snail x 10\nRewards\n70 EXP\n")
    kb = KnowledgeBase(play_kb)
    names = [q.name for q in quests.for_level(kb, 5, "Warrior", "Beginner")["now"]]
    assert names == ["Mai's Training"]


# ------------------------------------------------------------------ crafting

def test_crafting_rows(play_kb):
    lv1, lv2 = crafting.levels(KnowledgeBase(play_kb), "smithing")
    assert (lv1.level, lv1.needs_exp, lv1.char_level, lv2.recipes) == (1, 50, 10, [])
    koif = lv1.recipes[1]
    assert (koif.name, koif.exp, koif.catalyst, koif.net, koif.exp_per_meso, koif.mats) == \
        ("Metal Koif", 20, 1000, -1150, 0.017, "Mixed")
    assert koif.ingredients == [(1, "Bronze Koif"), (2, "Iron Ingot")]


# ------------------------------------------------------------------ build plan

def _guide_kb():
    return SimpleNamespace(get=lambda k: {"category": "guide"} if k == "guide/warrior-class-guide" else None)


@pytest.mark.parametrize("level,heading", [(9, "levels 1-10"), (10, "levels 10-30"), (11, "levels 10-30")])
def test_one_ap_table_at_a_boundary_level(level, heading):
    # level 10 is in both "levels 1-10" and "levels 10-30": the upcoming one, not both
    _, tables = buildplan.tables(_guide_kb(), "Warrior", "Warrior", level, "en")
    ap = [t for t in tables if t.kind == "ap"]
    assert len(ap) == 1 and heading in ap[0].heading
