"""The character's progress over time: the level chart's points, EXP per hour of play, and when the next
level (or a level goal) comes at this pace. The readings are store.ProgressLog's; the EXP table is the KB's."""
from __future__ import annotations

from . import plan

MAX_GAP = 2 * 3600       # readings further apart than this span a break, not play
MIN_HOURS = 5 / 60       # less play than this between readings says nothing about a pace
LAST = 20                # the pace of the latest stretches of play, not of the whole history


def points(samples: list[list]) -> list[tuple[float, float]]:
    """(time, level + the EXP bar's fraction) for the chart; a level without a reading counts from its start."""
    return [(t, lv + (pct or 0) / 100) for t, lv, pct in sorted(samples, key=lambda s: s[0])]


def exp_per_hour(kb, samples: list[list]) -> float | None:
    """EXP per hour of play from consecutive readings, the breaks between sessions left out."""
    readings = sorted((s for s in samples if s[2] is not None), key=lambda s: s[0])
    gained = hours = 0.0
    used = 0
    for (t0, lv0, p0), (t1, lv1, p1) in reversed(list(zip(readings, readings[1:]))):
        if not 0 < t1 - t0 <= MAX_GAP:
            continue
        a, b = plan.exp_position(kb, lv0, p0), plan.exp_position(kb, lv1, p1)
        if a is None or b is None or b < a:
            continue
        gained, hours, used = gained + b - a, hours + (t1 - t0) / 3600, used + 1
        if used >= LAST:
            break
    return gained / hours if hours >= MIN_HOURS and gained > 0 else None


def exp_to(kb, level: int, pct: float | None, target: int) -> float | None:
    """EXP from (level, EXP %) to the start of the target level; None past the KB's EXP table."""
    table = plan.exp_table(kb)
    if target <= level:
        return 0.0
    if any(lv not in table for lv in range(level, target)):
        return None
    return sum(table[lv] for lv in range(level, target)) - table[level] * (pct or 0) / 100


def hours_to(kb, level: int, pct: float | None, target: int, per_hour: float | None) -> float | None:
    left = exp_to(kb, level, pct, target)
    return left / per_hour if left is not None and per_hour else None


def duration(t, hours: float) -> str:
    """ "40 min" / "3.5 h" / "12 h" in the player's language."""
    if hours < 1:
        return t("prog_minutes", n=max(1, round(hours * 60)))
    return t("prog_hours", n=f"{hours:.1f}".removesuffix(".0") if hours < 10 else f"{round(hours):,}")
