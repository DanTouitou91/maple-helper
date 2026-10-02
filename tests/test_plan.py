"""The player's plan from the KB's guides: EXP left, where to train, the next job, and one tip."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from maplehelper import plan
from maplehelper.i18n import I18n

REAL_KB = Path(__file__).resolve().parent.parent / "data" / "kb"
t = I18n("en")


def char(**kw):
    base = dict(id="a", name="Kiwi", base_class="Thief", job="Thief", level=28, map="", exp_pct=None)
    return SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize("base,job,level,expected", [
    ("Thief", "Thief", 29, (["Assassin", "Bandit"], 30)),
    ("Magician", "Magician", 10, (["F/P Wizard", "I/L Wizard", "Cleric"], 30)),
    ("Thief", "Assassin", 34, None),                     # 3rd job is not in the launch build
    ("Magician", "F/P Mage", 80, None),
    ("Beginner", "Beginner", 7, (["Warrior", "Magician", "Bowman", "Thief"], 10)),
    ("Beginner", "Beginner", 14, (["Warrior", "Magician", "Bowman", "Thief"], 10)),   # still hasn't advanced
    ("Warrior", "Beginner", 5, (["Warrior"], 10)),       # planned Warrior, still a Beginner
    ("Magician", "Beginner", 8, (["Magician"], 10)),     # every 1st job opens at 10 in Classic World, Magician too
])
def test_next_job(base, job, level, expected):
    assert plan.next_job(base, job, level) == expected


@pytest.mark.parametrize("base,job,third", [
    ("Warrior", "Fighter", "Crusader"), ("Warrior", "Page", "White Knight"), ("Magician", "F/P Wizard", "F/P Mage"),
    ("Magician", "Cleric", "Priest"), ("Thief", "Assassin", "Hermit"), ("Bowman", "Crossbowman", "Sniper"),
])
def test_a_2nd_job_leads_to_its_own_3rd_job(monkeypatch, base, job, third):
    from maplehelper import jobs
    monkeypatch.setattr(jobs, "THIRD_JOB_OPEN", True)
    assert plan.next_job(base, job, 65) == ([third], 70)


def test_every_2nd_job_has_a_3rd_job_in_its_own_class():
    from maplehelper import jobs
    for tree in jobs.JOBS.values():
        for job, lv in tree:
            if lv == 30:
                assert (jobs.THIRD_JOB[job], 70) in tree, job


def test_every_1st_job_opens_at_10():
    """Nexon moved every 1st job advancement to level 10 (the KPQ guide's note): the Magician too."""
    from maplehelper import jobs
    for cls, tree in jobs.JOBS.items():
        if cls != "Beginner":
            assert (cls, 10) in tree, cls


def test_no_job_tip_for_3rd_job_before_it_is_in_the_game():
    tip = plan.tip(fake_kb(), char(job="Assassin", level=69), t)
    assert tip is None or tip.kind != "job"


GRIND = """Level 31-35
Map | Street | Max EXP/hr | Dominant mob | Portals to pots | Why
Line 2 <Area 1> | Kerning City Subway | 2,270,000 | Jr. Wraith (lv34) | 5 (Pharmacy) | Great.
The Burnt Land V | Warning Street | 1,080,714 | Fire Boar (lv32) | 8 (Store) | Fine.
Level 1-10
Map | Street | Max EXP/hr | Dominant mob | Portals to pots | Why
The Tree That Grew II | Victoria Road | 318,571 | Slime (lv6) | 3 (x) | Early.
"""
EXP = "Level | EXP to next | Cumulative\n34 | 155,540 | 1 |\n"


def fake_kb():
    pages = {plan.GRIND_GUIDE: GRIND, plan.EXP_GUIDE: EXP}
    entities = {"monster/9": {"category": "monster", "name": "Jr. Wraith", "props": {"EXP": 70}}}
    return SimpleNamespace(page=lambda k: pages.get(k, ""), entities=entities, get=entities.get)


def test_route_and_progress_from_the_guides():
    kb = fake_kb()
    best = plan.spots_for(kb, 33, 1)[0]
    assert (best.map, best.mob, best.mob_level) == ("Line 2 <Area 1>", "Jr. Wraith", 34)
    p = plan.progress(kb, 34, 50.0)
    assert p["left"] == 77770 and p["mob"] == "Jr. Wraith" and p["kills"] == 1111


def test_one_tip_at_a_time_job_first_then_map():
    kb = fake_kb()
    assert plan.tip(kb, char(level=28), t).kind == "job"
    assert plan.tip(kb, char(level=28), t, {"job": 28}) is None                 # hidden until the next level
    assert plan.tip(kb, char(level=29), t, {"job": 28}).kind == "job"
    low = char(base_class="Thief", job="Assassin", level=33, map="The Tree That Grew II")
    tip = plan.tip(kb, low, t)
    assert tip.kind == "map" and "Line 2 <Area 1>" in t(tip.key, **tip.args)


@pytest.mark.skipif(not (REAL_KB / "index.json").exists(), reason="no real knowledge base")
def test_real_guides_parse():
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(REAL_KB)
    assert len(plan.exp_table(kb)) >= 90 and len(plan.brackets(kb)) >= 10
    assert plan.class_guide(kb, "Magician", "F/P Wizard") == "guide/fp-wizard-class-guide"
