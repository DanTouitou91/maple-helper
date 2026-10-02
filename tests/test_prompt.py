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
    assert "old answer 11" in convo and "old question 7" in convo      # this session's last 6 exchanges
    assert "old question 6" not in convo                                 # older ones live in the summaries


def test_long_answers_are_trimmed_in_the_recent_conversation(kb, isolated_store):
    from maplehelper.brain import build_prompt
    from maplehelper.store import History
    h = History("c1")
    h.append("user", "Q" * 700)
    h.append("assistant", "A" * 900)
    convo = build_prompt("hi", None, h, kb, has_screenshot=False).split("<recent_conversation>")[1]
    assert "Q" * 600 in convo and "Q" * 601 not in convo
    assert "A" * 400 in convo and "A" * 401 not in convo
