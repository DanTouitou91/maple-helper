"""Instant answers from the KB: only simple, unambiguous factual questions; the rest goes to Claude."""
import pytest

from maplehelper import quick
from maplehelper.i18n import I18n

t = I18n("en")


def first_monster(kb):
    return next(k for k, e in kb.entities.items() if e["category"] == "monster" and (e.get("props") or {}).get("HP"))


def test_stat_question_is_answered_from_the_kb(kb):
    key = first_monster(kb)
    e = kb.get(key)
    ans = quick.answer(f"how much HP does {e['name']} have?".replace("how ", "what's the "), kb, t)
    assert ans and f"HP: {e['props']['HP']}" in ans.text and ans.entities == [key]


def test_hebrew_stat_question(kb):
    key = first_monster(kb)
    e = kb.get(key)
    ans = quick.answer(f"כמה HP יש ל-{e['name']}?", kb, t)
    assert ans and str(e["props"]["HP"]) in ans.text


@pytest.mark.parametrize("q", [
    "how should I level my Assassin?",      # judgement
    "מה כדאי לעשות בלבל 30?",                 # judgement, nothing named
    "what is this monster?",                 # needs the screenshot
    "tell me everything about the game and all the monsters you know please",  # long
])
def test_everything_else_goes_to_claude(kb, q):
    assert quick.answer(q, kb, t) is None


def test_hebrew_words_match_whole_words_only():
    assert quick.WHO.search("מי מפיל את זה")
    assert not quick.WHO.search("מימון")


def test_a_name_containing_a_stat_word_is_not_a_stat_question():
    # "לבלו סנייל" (Blue Snail) contains "לבל" (level) but doesn't ask about the level
    level = next(rx for rx, key, _ in quick.STATS if key == "Level")
    assert not level.search("כמה HP יש לבלו סנייל?")
    assert level.search("באיזה לבל Mano?") and level.search("what level is Mano")


def test_how_much_is_a_number_question(kb):
    # the module docstring's own example used to fall through to Claude because of "how"
    ans = quick.answer("How much HP does Red Snail have?", kb, t)
    assert ans and "HP: 45" in ans.text
    assert quick.answer("how do I kill Red Snail?", kb, t) is None


def test_hebrew_stat_word_with_the_article(kb):
    # "מה הלבל של..." / "מה הדיוק של...": the definite article is glued to the stat word
    ans = quick.answer("מה הלבל של רד סנייל?", kb, t)
    assert ans and "Level: 4" in ans.text


def test_defense_reads_physical_defense(kb):
    # monsters carry "Physical Defense" (and "Magic Defense"), never a plain "Defense"
    kb.get("monster/130101")["props"]["Physical Defense"] = 20
    ans = quick.answer("Red Snail defense", kb, t)
    assert ans and "Defense: 20" in ans.text


def test_two_questions_in_one_go_to_claude(kb):
    # answering only the drops of "level and drops" would look like the whole answer
    assert quick.answer("Red Snail level and drops", kb, t) is None
    assert quick.answer("where is Red Snail and what's its HP", kb, t) is None


@pytest.mark.parametrize("q", [
    "When does Red Snail spawn?",
    "Red Snail spawn time",
    "Red Snail respawn",
    "How many Red Snail to level up",
    "Red Snail exp per hour",
    "Red Snail exp at level 10",
    "how many Red Snail for level 10",
    "מתי רד סנייל עושה ספאון?",
    "כמה רד סנייל צריך כדי לעלות לבל?",
    "כמה אקספי לשעה ברד סנייל?",
    "כמה אקספי נותן רד סנייל בלבל 10?",
])
def test_times_rates_and_levelling_go_to_claude(kb, q):
    # the page's EXP or level is not "per hour" or "to level up": those need the player's numbers
    assert quick.answer(q, kb, t) is None


def test_where_still_lists_the_maps(kb):
    ans = quick.answer("Where does Red Snail spawn?", kb, t)
    assert ans and "Henesys Hunting Ground I" in ans.text


@pytest.mark.parametrize("q,expected", [
    ("Red Snail's HP", "HP: 45"),
    ("What is Red Snail's level?", "Level: 4"),
    ("Red Snail’s EXP", "EXP: 8"),
])
def test_possessive_names_are_found(kb, q, expected):
    ans = quick.answer(q, kb, t)
    assert ans and ans.text.endswith(expected) and ans.entities == ["monster/130101"]


def test_a_missing_stat_is_not_half_answered(kb):
    # the fixture has no MP: "HP and MP" answered with HP alone would look like the whole answer
    assert quick.answer("Red Snail HP and MP", kb, t) is None
    assert "HP: 45" in quick.answer("Red Snail HP and EXP", kb, t).text
