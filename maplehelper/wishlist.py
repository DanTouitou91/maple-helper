"""Items a player is hunting for, per character: who drops them, and a heads-up when the KB changes them
or their Free Market price drops."""
from __future__ import annotations

import time


def items(settings, cid: str | None) -> list[str]:
    return list((settings["wishlist"] or {}).get(cid or "", []))


def toggle(settings, cid: str | None, key: str) -> bool:
    """Add or remove; returns True when the item is now on the list."""
    if not cid:
        return False
    data = dict(settings["wishlist"] or {})
    keys = list(data.get(cid, []))
    wished = key not in keys
    keys = keys + [key] if wished else [k for k in keys if k != key]
    data[cid] = keys
    settings["wishlist"] = data
    return wished


def touched(entries: list[dict], keys: list[str], kb) -> list[str]:
    """Names of wished items that a KB update added, removed, changed, or whose drops changed."""
    names = {k: (kb.get(k) or {}).get("name") for k in keys}
    wanted = {n for n in names.values() if n}
    hit: list[str] = []

    def add(name):
        if name and name not in hit:
            hit.append(name)
    for e in entries:
        for kind in ("added", "removed", "changed", "updated"):
            for r in e.get(kind, []):
                if r.get("key") in names:
                    add(r.get("name"))
                for item in r.get("drops_added", []) + r.get("drops_removed", []) + r.get("drops_confirmed", []):
                    if item in wanted:
                        add(item)
    return hit


PRICE_DROP = 0.15      # a Free Market median this much under the one remembered is worth a heads-up


def price_seen(settings, key: str, median: int | None, now: float | None = None) -> tuple[dict, bool]:
    """Remember an item's latest Free Market median. Returns its record ({"median", "t", and "was": the median
    before a drop, while the price stays down}) and whether this is a new drop to announce (once per drop)."""
    data = dict(settings["wish_prices"] or {})
    old = data.get(key) or {}
    if not median:
        return old, False
    rec = {"median": int(median), "t": now if now is not None else time.time()}
    was = old.get("was")
    if was and median <= was * (1 - PRICE_DROP):
        rec.update(was=was, alerted=old.get("alerted", False))         # still down since the same drop
    elif old.get("median") and median <= old["median"] * (1 - PRICE_DROP):
        rec.update(was=old["median"], alerted=False)
    news = bool(rec.get("was")) and not rec.get("alerted")
    if news:
        rec["alerted"] = True
    data[key] = rec
    settings["wish_prices"] = data
    return rec, news
