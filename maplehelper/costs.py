"""What API-key answers cost, per calendar month (local only; a subscription login has no per-answer cost)."""
from __future__ import annotations

import threading
import time

from . import store

_lock = threading.Lock()          # the overlay writes from a background thread


def path():
    return store.DATA_DIR / "costs.json"


def month(when: float | None = None) -> str:
    return time.strftime("%Y-%m", time.localtime(when))


def add(usd: float, when: float | None = None) -> None:
    """Count one answer's cost in its month ({"2026-10": 0.123, ...})."""
    if not usd or usd <= 0:
        return
    with _lock:
        data = store._read_json(path(), {})
        data = data if isinstance(data, dict) else {}
        key = month(when)
        data[key] = round(float(data.get(key) or 0) + usd, 6)
        store._write_json(path(), data)


def month_total(when: float | None = None) -> float:
    data = store._read_json(path(), {})
    v = data.get(month(when)) if isinstance(data, dict) else None
    return float(v) if isinstance(v, (int, float)) else 0.0


def label(usd: float) -> str:
    """"$0.004": a tenth of a cent still shows."""
    return f"${usd:.3f}" if usd < 1 else f"${usd:.2f}"
