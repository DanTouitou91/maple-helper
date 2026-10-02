"""The system prompt is a str.format template: literal JSON braces must be doubled."""
from maplehelper.brain import LENGTH, SYSTEM_PROMPT


def test_system_prompt_formats():
    for length in LENGTH.values():
        text = SYSTEM_PROMPT.format(length=length)
        assert "drop_groups" in text and "{length}" not in text


def test_question_and_tagged_card_are_sent_once(kb, isolated_store):
    from maplehelper.brain import build_prompt
    from maplehelper.store import History
    h = History("c1")
    for i in range(12):
        h.append("user", f"old question {i}")
        h.append("assistant", f"old answer {i}")
    q = "where does Red Snail live?"
    h.append("user", f"[about Red Snail] {q}")         # the chat logs the question before asking
    p = build_prompt(q, None, h, kb, has_screenshot=False, focus=["monster/130101"])
    assert p.count(q) == 1                              # only in <question>
    assert p.count("\n[monster/130101]\n") == 1         # the tagged card's page, not again as a mention
    convo = p.split("<recent_conversation>")[1].split("</recent_conversation>")[0]
    assert "old answer 11" in convo and "old question 8" not in convo   # the last few messages only
