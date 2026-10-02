"""👍/👎 on answers, kept only on this PC (nothing is sent anywhere). tools/feedback_evals.py turns the 👎 ones
into draft eval cases for evals/answers.json."""
from __future__ import annotations

import threading
import time

from . import store

KEEP = 500                        # the newest ratings; older ones fall off
_lock = threading.Lock()          # the overlay writes from a background thread


def path():
    return store.DATA_DIR / "feedback.json"


def load(p=None) -> list[dict]:
    data = store._read_json(p or path(), [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def add(question: str, answer: str, rating: str, entities: list[str] | None = None, model: str | None = None,
        lang: str = "he", when: float | None = None) -> dict:
    """rating: "up" | "down"."""
    rec = {"question": question, "answer": answer, "rating": rating, "entities": list(entities or []),
           "model": model or "", "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(when)), "lang": lang}
    with _lock:
        store._write_json(path(), (load() + [rec])[-KEEP:])
    return rec
