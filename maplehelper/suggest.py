"""What the chat offers to ask: starter questions on an empty chat, follow-ups under an answer's cards,
and the play-tools page an answer belongs to. No Qt and no AI: the KB and the character only."""
from __future__ import annotations

import re

from . import plan

NEAR = 3              # a starter monster is at most this many levels from the player


def _monster_near(kb, level: int) -> str | None:
    """A monster worth asking about: the level's best training mob, else the nearest one that drops something."""
    rows = []
    for k, e in kb.entities.items():
        lv = (e.get("props") or {}).get("Level") if e["category"] == "monster" else None
        if isinstance(lv, (int, float)) and abs(lv - level) <= NEAR:
            rows.append((abs(lv - level), e["name"], k))
    rows.sort()
    best = (plan.spots_for(kb, level, 1) or [None])[0]
    if best:
        rows.sort(key=lambda r: r[1] != best.mob)          # stable: the training mob first, then by distance
    return next((name for _, name, k in rows[:4] if kb.monster_drops(k)), None)


def starters(kb, c, t, n: int = 4) -> list[str]:
    """3-4 questions for an empty chat, fitted to the character (level, job, map)."""
    out = [t("sug_train")]
    if c is None:
        return out + [t("sug_quests")]
    nxt = plan.next_job(c.base_class, c.job, c.level)
    if nxt and c.level >= nxt[1] - 5:                      # the advancement is close enough to plan for
        choices, lv = nxt
        out.append(t("sug_job_one", job=choices[0]) if len(choices) == 1 else t("sug_job_pick", level=lv))
    elif c.map:
        out.append(t("sug_map", map=c.map))
    mob = _monster_near(kb, c.level)
    if mob:
        out.append(t("sug_drops", name=mob))
    out.append(t("sug_quests"))
    return out[:n]


# the subject card's kind -> follow-up questions (i18n keys); "level" only makes sense with a character
FOLLOW_UPS = {
    "monster": ("fu_where", "fu_level", "fu_drops"),
    "item": ("fu_who_drops", "fu_buy"),
    "map": ("fu_get_there", "fu_map_mobs"),
    "quest": ("fu_quest_how",),
    "npc": ("fu_npc_where",),
}


def follow_ups(entities: list[str], drop_groups: list[dict] | None = None) -> tuple[str, list[str]] | None:
    """(the main entity, its follow-up i18n keys) for an answer's cards, or None.
    The main entity is the first subject card (as the chat shows it), else the first card."""
    keys = list(entities or []) or [g["monster"] for g in drop_groups or []]
    if not keys:
        return None
    main = next((k for k in keys if k.split("/")[0] in ("monster", "npc", "map", "quest")), keys[0])
    found = FOLLOW_UPS.get(main.split("/")[0])
    return (main, list(found)) if found else None


# play-tools page -> words in the question (Hebrew and English). The first match wins, so the narrow ones go first.
TOOL_WORDS = [
    ("calc", r"פגיע|נזק|דיוק|מפספס|\bmiss|\bhits?\b|accuracy|\bacc\b|damage|\bdmg\b"),
    ("crafting", r"קראפט|סמית|טיילור|craft|smith|tailor"),
    ("prices", r"מחיר|כמה עולה|כמה שווה|למכור|price|\bsell"),
    ("build", r"בילד|\bAP\b|\bSP\b|\bbuild|skill points"),
    ("quests", r"קווסט|משימ|quest"),
    ("train", r"לאמן|אימון|לטחון|גרינד|לעלות לבל|\btrain|grind|level(?:ing)? up|exp/h"),
]


def tools_page(question: str, entities: list[str] | None = None) -> str | None:
    """The play-tools page that answers this kind of question better (with numbers for the character), or None."""
    for page, words in TOOL_WORDS:
        if re.search(words, question or "", re.I):
            return page
    if any(k.startswith("quest/") for k in entities or []):
        return "quests"
    return None
