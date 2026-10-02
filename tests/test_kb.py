"""Knowledge-base lookup against the fixture KB."""


def test_loads_index_and_aliases(kb):
    assert len(kb.entities) == 15
    assert kb.get("map/100000000")["name"] == "Henesys"


def test_longest_name_wins(kb):
    # "Red Snail" must not also report "Snail"
    assert kb.find_mentions("where do I find Red Snail?") == ["monster/130101"]
    assert kb.find_mentions("snails and a snail") == ["monster/100100"]


def test_multiple_mentions_in_order_of_length(kb):
    found = kb.find_mentions("Red Potion from a Blue Snail in Henesys")
    assert set(found) == {"item/2000000", "monster/100101", "map/100000000"}


def test_hebrew_alias_and_prefix(kb):
    assert kb.find_mentions("איפה רד סנייל?") == ["monster/130101"]
    assert kb.find_mentions("מה יש בהנסיס") == ["map/100000000"]      # ב + הנסיס


def test_resolve_names_after_speech_to_text(kb):
    assert kb.resolve_names("איפה חילזון אדום ליד הנסיס") == "איפה Red Snail ליד Henesys"
    # a glued Hebrew prefix is kept and hyphenated: "בהנסיס" -> "ב-Henesys"
    assert kb.resolve_names("מה יש בהנסיס") == "מה יש ב-Henesys"
    assert kb.resolve_names("ורד סנייל") == "ו-Red Snail"
    # but an alias inside a longer Hebrew word is left alone
    assert kb.resolve_names("אבגדהנסיסים") == "אבגדהנסיסים"


def test_page_body_strips_front_matter(kb):
    body = kb.page_body("monster/130101")
    assert body.startswith("# Red Snail") and "---" not in body[:5]
    assert kb.page("monster/0") == ""


def test_image_path(kb):
    assert kb.image_path("monster/130101").name == "130101.png"
    assert kb.image_path("monster/100100") is None           # listed but file missing
    assert kb.image_path("item/2000000") is None


def test_level_digest(kb):
    d = kb.level_digest(5)
    assert "Red Snail | 4 | 45 | 8 | Henesys Hunting Ground I, Snail Garden, Henesys Hunting Ground II" in d
    assert "Axe Stump" not in d                              # level 17 is outside 5-5..5+8
    assert kb.level_digest(200) == ""


def test_missing_kb_is_empty(tmp_path):
    from maplehelper.kb import KnowledgeBase
    empty = KnowledgeBase(tmp_path)
    assert empty.entities == {} and empty.find_mentions("Red Snail") == []


def test_top_maps_stop_at_the_end_of_the_map_table(kb_copy):
    # a one-map monster: the "Change history" table under it has numeric rows that are not maps
    from maplehelper.kb import KnowledgeBase
    page = kb_copy / "pages" / "monster" / "130101.md"
    text = page.read_text(encoding="utf-8").split("Snail Garden")[0].rstrip()
    page.write_text(text + "\nChange history\nupdated in COT2 ▾ Stat | COT1 | COT2 | Change\n"
                    "HP | 7,560 | 7,420 | -140\nP.DMG | 101 | 252 | +151\n", encoding="utf-8")
    assert KnowledgeBase(kb_copy)._top_maps("monster/130101") == ["Henesys Hunting Ground I"]


def test_drop_sort_survives_a_non_numeric_level(kb_copy):
    import json
    from maplehelper.kb import KnowledgeBase
    idx = kb_copy / "index.json"
    entities = json.loads(idx.read_text(encoding="utf-8"))
    for e in entities:
        if e["key"] == "monster/100101":
            e["props"]["Level"] = "?"
    idx.write_text(json.dumps(entities), encoding="utf-8")
    kb = KnowledgeBase(kb_copy)
    kb.monster_drops = lambda key: ["item/2000000"]                # every monster drops it
    assert kb.droppers["item/2000000"][-1] == "monster/100101"     # unknown level sorts last
    assert kb.drop_groups(["item/2000000"])[0]["monster"] == "monster/100100"


def test_drop_table_is_written_once_when_missing(kb_copy):
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(kb_copy)
    kb.ensure_drop_table()
    table = kb_copy / "drops.tsv"
    assert table.read_text(encoding="utf-8").startswith("monster\tmonster_level")
    table.unlink()
    kb.ensure_drop_table()                  # checked once per loaded KB, not on every question
    assert not table.exists()


def test_an_older_drop_table_without_the_source_column_is_rebuilt(kb_copy):
    """An unpacked update makes an old 6-column table newer than index.json: the header decides, not the time."""
    from maplehelper.kb import KnowledgeBase
    table = kb_copy / "drops.tsv"
    table.write_text("monster\tmonster_level\tmonster_key\titem\titem_type\titem_key\nSnail\t1\tmonster/1\tX\tEtc\titem/1",
                     encoding="utf-8")
    assert KnowledgeBase(kb_copy).ensure_drop_table() is True
    assert table.read_text(encoding="utf-8").split("\n")[0].endswith("\titem_key\tsource")


def test_the_prompt_promises_the_source_column_only_when_the_table_has_it(kb_copy, monkeypatch):
    from maplehelper import kb as kbmod
    from maplehelper.brain import Brain
    (kb_copy / "drops.tsv").write_text("monster\tmonster_level\tmonster_key\titem\titem_type\titem_key\n",
                                       encoding="utf-8")
    assert "item key, source)" in Brain(kbmod.KnowledgeBase(kb_copy)).system_prompt()      # rebuilt with it
    (kb_copy / "drops.tsv").write_text("monster\tmonster_level\tmonster_key\titem\titem_type\titem_key\n",
                                       encoding="utf-8")
    monkeypatch.setattr(kbmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(kbmod, "BUNDLED_KB", kb_copy)             # the installed app's copy: never rewritten
    prompt = Brain(kbmod.KnowledgeBase(kb_copy)).system_prompt()
    assert "item key)" in prompt and "source" not in prompt.split("drops.tsv")[1].split("Grep")[0]


def test_drop_table_never_written_into_the_installed_app(kb_copy, monkeypatch):
    from maplehelper import kb as kbmod
    monkeypatch.setattr(kbmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(kbmod, "BUNDLED_KB", kb_copy)
    kbmod.KnowledgeBase(kb_copy).ensure_drop_table()
    assert not (kb_copy / "drops.tsv").exists()


def test_drop_table_in_a_read_only_folder_is_skipped(kb_copy, monkeypatch):
    from pathlib import Path
    from maplehelper.kb import KnowledgeBase

    def denied(*_a, **_k):
        raise PermissionError("read-only")
    monkeypatch.setattr(Path, "write_text", denied)
    KnowledgeBase(kb_copy).ensure_drop_table()              # no crash, no file
    assert not (kb_copy / "drops.tsv").exists()
