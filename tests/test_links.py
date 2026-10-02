"""The browser opens only the sites the app knows: URLs come from the KB and GitHub's API, not from the app."""
import json
import os

import pytest

from maplehelper import links


@pytest.mark.parametrize("url", ["https://meowdb.com/msclassic/monster/100100", "https://www.meowdb.com/x?q=Red+Potion",
                                 "https://github.com/DanTouitou91/maple-helper/releases/tag/v0.4.0",
                                 " https://meowdb.com/trimmed "])
def test_known_sites_open(url, monkeypatch):
    opened = []
    monkeypatch.setattr(links.webbrowser, "open", lambda u: opened.append(u))
    assert links.open_url(url) and opened == [url.strip()]


@pytest.mark.parametrize("url", ["http://meowdb.com/x", "file:///etc/passwd", "javascript:alert(1)", "notaurl:whatever",
                                 "https://evil.com/meowdb.com", "https://meowdb.com.evil.com/", "https://meowdb.com@evil.com/",
                                 "https://github.com/someone-else/repo", "https://github.com/", "", None, 5,
                                 "https://[bad"])
def test_everything_else_is_refused_silently(url, monkeypatch):
    opened = []
    monkeypatch.setattr(links.webbrowser, "open", lambda u: opened.append(u))
    assert links.safe_url(url) is None and links.open_url(url) is False and opened == []


def test_entity_card_opens_only_a_known_site(kb_copy, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QToolButton
    QApplication.instance() or QApplication([])
    from maplehelper.kb import KnowledgeBase
    from maplehelper.ui import theme
    from maplehelper.ui.widgets import EntityCard
    index = json.loads((kb_copy / "index.json").read_text(encoding="utf-8"))
    index[0]["url"] = "file:///C:/Users/me/secret.txt"
    (kb_copy / "index.json").write_text(json.dumps(index), encoding="utf-8")
    kb = KnowledgeBase(kb_copy)
    opened = []
    monkeypatch.setattr(links.webbrowser, "open", lambda u: opened.append(u))

    def open_button(card):
        return [b for b in card.findChildren(QToolButton) if b.text() == theme.ICON["open"]]
    assert not open_button(EntityCard(kb, index[0]["key"], "en"))       # a bad URL: no ↗ at all
    good = EntityCard(kb, index[1]["key"], "en")
    open_button(good)[0].click()
    assert opened == [index[1]["url"]]
