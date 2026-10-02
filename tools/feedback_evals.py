"""Turn the 👎 answers a player saved (feedback.json in the app's data folder) into draft eval cases.

    python tools/feedback_evals.py <path to feedback.json> [--out evals/feedback_drafts.json] [--kb data/kb]

The app keeps 👍/👎 only on the player's PC; a player (or you, from your own install) shares the file by hand.
Each 👎 question not already in evals/answers.json becomes a case in the answers.json format, with the bad
answer in its "note". Checks start from what the KB says the question names (must_mention) and are left empty
when it names nothing: fill them from data/kb (docs/EVALS.md), then move the case into evals/answers.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from eval_answers import CASES, KB, load_cases, validate_cases  # noqa: E402

DRAFTS = ROOT / "evals" / "feedback_drafts.json"
# the case kind from the question's words (the first match wins); a plain judgement call otherwise
KIND_WORDS = [
    ("who_drops", r"(מאיז[הו]|מאילו|איזה|אילו)\s+מפלצ|מי\s+מפיל|which\s+monsters?|who\s+drops"),
    ("drops", r"דרופ|מפיל|נופל|drops?\b|loot"),
    ("training", r"לאמן|אימון|גרינד|train|grind"),
    ("quest", r"קווסט|quest"),
    ("job", r"ג'וב|ג׳וב|job|advance"),
    ("where", r"איפה|באיזו מפה|where"),
    ("stats", r"כמה\s+(HP|חיים|EXP|נזק)|\bhp\b|\bexp\b|what level"),
]


def _kind(question: str) -> str:
    return next((kind for kind, words in KIND_WORDS if re.search(words, question, re.I)), "judgement")


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def drafts(feedback: list[dict], existing: list[dict], kb=None) -> list[dict]:
    """Draft cases for the 👎 entries (one per question, skipping questions answers.json already has)."""
    seen = {_norm(c["question"]) for c in existing}
    ids = {c["id"] for c in existing}
    out = []
    for i, fb in enumerate(feedback):
        q = (fb.get("question") or "").strip()
        if fb.get("rating") != "down" or not q or _norm(q) in seen:
            continue
        seen.add(_norm(q))
        day = re.sub(r"\D", "", fb.get("date") or "")[:8] or "0"
        cid = f"fb-{day}-{i + 1}"
        while cid in ids:
            cid += "-x"
        ids.add(cid)
        names = [kb.get(k)["name"] for k in kb.find_mentions(q, 4)] if kb else []
        answer = re.sub(r"\s+", " ", fb.get("answer") or "")[:300]
        out.append({"id": cid, "question": q, "lang": fb.get("lang") if fb.get("lang") in ("he", "en") else "he",
                    "kind": _kind(q),
                    "note": f"👎 from a player ({fb.get('model') or 'unknown model'}, {fb.get('date') or '?'}): "
                            f"\"{answer}\". Fill the checks from data/kb before moving this into answers.json.",
                    "checks": {"must_mention": names} if names else {}})
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Hebrew on a Windows console
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Draft eval cases from the app's 👎 answers.")
    ap.add_argument("feedback", type=Path, help="feedback.json from the app's data folder")
    ap.add_argument("--out", type=Path, default=DRAFTS)
    ap.add_argument("--cases", type=Path, default=CASES)
    ap.add_argument("--kb", type=Path, default=KB)
    args = ap.parse_args(argv)

    from maplehelper import feedback
    from maplehelper.kb import KnowledgeBase

    entries = feedback.load(args.feedback)
    if not entries:
        print(f"no ratings in {args.feedback}")
        return 2
    kb = KnowledgeBase(args.kb) if (args.kb / "index.json").exists() else None
    cases = drafts(entries, load_cases(args.cases), kb)
    args.out.write_text(json.dumps({"about": "Drafts from players' 👎 answers: fill the checks, then move each "
                                             "case into evals/answers.json (docs/EVALS.md).", "cases": cases},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(cases)} draft case(s) from {sum(e.get('rating') == 'down' for e in entries)} 👎 -> {args.out}")
    for p in validate_cases(cases):
        print("  to do: " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
