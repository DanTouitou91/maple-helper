"""Text the app didn't write (KB names, AI strings) is shown as text, never read as HTML (offscreen Qt).

A name carrying "<img src=file://...>" would make Qt load the file on render (on Windows a UNC path leaks the
NTLM hash); "<span style=color:red>" would restyle it. Every widget that shows such a string renders it literally.
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

HOSTILE = '<img src="file:///nonexistent/x.png"><span style="color:#ff0000">RED</span>'
ANGLED = "The Forest of Patience <Step 1>"       # a real map name: shown whole, not read as a tag
MONSTER, MAP, ITEM = "monster/666", "map/777", "item/2000000"


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from maplehelper.ui import terms, theme
    theme.set_mode("light")
    terms.LANG = "en"
    return app


@pytest.fixture
def hostile_kb(kb_copy):
    """The fixture KB plus a monster with a hostile name (it drops Red Potion) and a map with angle brackets."""
    from maplehelper.kb import KnowledgeBase
    index = json.loads((kb_copy / "index.json").read_text(encoding="utf-8"))
    index += [{"key": MONSTER, "name": HOSTILE, "category": "monster", "url": "https://meowdb.com/x", "props": {"Level": 3}},
              {"key": MAP, "name": ANGLED, "category": "map", "url": "https://meowdb.com/y", "props": {}}]
    (kb_copy / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (kb_copy / "pages" / "monster" / "666.md").write_text(       # it drops Red Potion and lives on the angled map
        "---\n---\nDrops (MS Classic)\nRed Potion\nMap Locations\nMap Region | Count | Share | Types | Mob Rate | Respawn\n"
        f"{ANGLED} | 3 | 100% | - | - | -\n", encoding="utf-8")
    return KnowledgeBase(kb_copy)


def red_pixels(qapp, widget) -> int:
    widget.show()
    qapp.processEvents()
    img = widget.grab().toImage()
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if (c := img.pixelColor(x, y)).red() > 200 and c.green() < 60 and c.blue() < 60)


def labels(widget, name: str):
    from PySide6.QtWidgets import QLabel
    return [lb for lb in widget.findChildren(QLabel) if lb.objectName() == name]


def widgets_showing(kb, name: str):
    """Every widget type that shows a KB or AI string, each holding `name`."""
    from maplehelper.i18n import I18n
    from maplehelper.store import Character
    from maplehelper.ui import chatbits, patchnotes, plancard, toast, widgets
    from maplehelper.ui.controls import Section
    from maplehelper.ui.guides import GuideRow
    from maplehelper.ui.pinsview import HistoryDialog
    from maplehelper.ui.wishlist import WishlistDialog
    t = I18n("en")
    key = next(k for k, e in kb.entities.items() if e["name"] == name)
    out = {"tile": widgets.EntityTile(kb, key), "card": widgets.EntityCard(kb, key, "en"),
           "group": widgets.DropGroupCard(kb, key, [ITEM]), "grid": widgets.TileGrid(kb, [key], title="Drops of " + name),
           "system": widgets.SystemLine("Profile updated: job " + name),
           "notice": widgets.NoticeCard("Wishlist changed: " + name, "Show", False),
           "bubble_tag": widgets.Bubble("q", "user", False, tag=name),
           "answer": widgets.Bubble("Go to " + name + " now", "assistant", False),
           "chips": chatbits.Chips(), "section": Section("x", rtl=False), "tip": plancard.TipStrip(),
           "change": patchnotes.ChangeCard(kb, {"key": key, "name": name}, name, [name], False),
           "guide": GuideRow(kb, {"key": "guide/leveling", "title": name, "category": "general", "minutes": None}, t, False),
           "toast": toast.Toast(name, name, False, "Arial"),
           "history": HistoryDialog([{"q": name, "a": name, "t": 0}], name, "en", ""),
           "wishlist": WishlistDialog([ITEM], kb, "en", "")}      # lists the monster that drops it
    profile = widgets.ProfileCard()
    profile.show_character(Character(id="a", name=name, base_class="Warrior", job=name, level=3, map=name), None, kb, False)
    out["profile"] = profile
    out["chips"].set_title(name, False)
    out["section"].add_row(name, hint=name)
    from maplehelper import plan
    out["tip"].show_tip(plan.Tip("map", "tip_map", {"map": name, "mob": name}, "q"), t, False)
    return out


def test_a_hostile_kb_name_renders_as_text_everywhere(qapp, hostile_kb):
    from maplehelper.ui.widgets import plain_tip
    shown, plain = widgets_showing(hostile_kb, HOSTILE), widgets_showing(hostile_kb, "Snail")
    for what, w in shown.items():
        assert red_pixels(qapp, w) == red_pixels(qapp, plain[what]), what      # the app's logo has red: same as a plain name
    assert labels(shown["tile"], "TileName")[0].text() == HOSTILE
    assert labels(shown["card"], "CardName")[0].text() == HOSTILE
    assert shown["tile"].toolTip() == plain_tip(HOSTILE) and "<img" not in shown["tile"].toolTip()
    # the AI's answer: markup applied only after the text is escaped, so no tag survives
    html = shown["answer"].label.text()
    assert "<img" not in html and "&lt;img" in html and not shown["answer"].label.openExternalLinks()
    from maplehelper.store import Character
    from maplehelper.ui.pinsview import character_card_image

    def share_card_red(name):
        c = Character(id="a", name=name, base_class="Warrior", job=name, level=3, map=name)
        img = character_card_image(c, None, hostile_kb, None, None).toImage()
        return sum(1 for y in range(img.height()) for x in range(img.width())
                   if (p := img.pixelColor(x, y)).red() > 200 and p.green() < 60 and p.blue() < 60)
    assert share_card_red(HOSTILE) == share_card_red("Snail")


def test_a_name_with_angle_brackets_is_shown_whole(qapp, hostile_kb):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    import html
    shown = widgets_showing(hostile_kb, ANGLED)
    for what, w in shown.items():
        w.show()
        lbs = w.findChildren(QLabel) + ([w] if isinstance(w, QLabel) else [])
        # as plain text, or escaped inside a rich-text label (the chat bubble): shown whole either way
        assert any(ANGLED in lb.text() and lb.textFormat() == Qt.PlainText
                   or html.escape(ANGLED) in lb.text() and lb.textFormat() == Qt.RichText for lb in lbs), what
        assert not any(ANGLED in lb.text() and lb.textFormat() != Qt.PlainText for lb in lbs), what
    assert labels(shown["grid"], "TileGridTitle")[0].text() == "Drops of " + ANGLED


def test_ai_answer_markup_never_becomes_html():
    from maplehelper import bidi, glossary
    html = bidi.to_html("Go to " + HOSTILE + " **now**")
    assert "<img" not in html and "&lt;img" in html and "<b>now</b>" in html
    assert "<img" not in glossary.annotate(html, "en")          # the "?" badges go only after glossary terms
