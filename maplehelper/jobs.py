"""The MapleStory Classic job tree (no Qt here: the plan and the dialogs both read it)."""
from __future__ import annotations

# base class -> [(job, min level)]
JOBS = {
    "Beginner": [("Beginner", 1)],
    "Warrior": [("Beginner", 1), ("Warrior", 10), ("Fighter", 30), ("Page", 30), ("Spearman", 30),
                ("Crusader", 70), ("White Knight", 70), ("Dragon Knight", 70)],
    "Magician": [("Beginner", 1), ("Magician", 10), ("F/P Wizard", 30), ("I/L Wizard", 30), ("Cleric", 30),
                 ("F/P Mage", 70), ("I/L Mage", 70), ("Priest", 70)],
    "Bowman": [("Beginner", 1), ("Bowman", 10), ("Hunter", 30), ("Crossbowman", 30), ("Ranger", 70), ("Sniper", 70)],
    "Thief": [("Beginner", 1), ("Thief", 10), ("Assassin", 30), ("Bandit", 30), ("Hermit", 70), ("Chief Bandit", 70)],
}
# each 2nd job has one 3rd job: a Fighter becomes a Crusader, never a White Knight (the class guides' "At level 70")
THIRD_JOB = {"Fighter": "Crusader", "Page": "White Knight", "Spearman": "Dragon Knight", "F/P Wizard": "F/P Mage",
             "I/L Wizard": "I/L Mage", "Cleric": "Priest", "Hunter": "Ranger", "Crossbowman": "Sniper",
             "Assassin": "Hermit", "Bandit": "Chief Bandit"}
# Nexon's August 21 report: 3rd Job Advancement is not in Founder's Access or Grand Launch (release-date guide)
THIRD_JOB_OPEN = False


def jobs_for(base_class: str, level: int) -> list[str]:
    return [j for j, lv in JOBS.get(base_class, []) if lv <= level]
