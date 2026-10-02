"""Finding the game window by its title: the game itself, never a browser tab, video or chat about it."""
import pytest

from maplehelper.capture import looks_like_game


@pytest.mark.parametrize("title,app", [
    ("MapleStory Classic", ""),
    ("MapleStory", ""),
    ("MapleStory Classic World", ""),
    ("", "MapleStory"),                                   # macOS without Screen Recording: only the app's name
    ("MapleStory Classic", "wine64-preloader"),           # CrossOver / Wine
])
def test_the_game(title, app):
    assert looks_like_game(title, app)


@pytest.mark.parametrize("title,app", [
    ("MapleStory Classic drops - Google Chrome", ""),
    ("MapleStory Classic World guide — Mozilla Firefox", ""),
    ("MapleStory Classic — Mozilla Firefox Private Browsing", ""),
    ("MapleStory Classic and 3 more pages - Personal - Microsoft​ Edge", ""),
    ("MapleStory Classic - Brave", ""),
    ("MapleStory Classic | NiaMeowDB - Opera", ""),
    ("Bossing in MapleStory Classic - YouTube", ""),
    ("#maplestory-classic | Guild - Discord", ""),
    ("Discord | #maplestory | Guild", ""),
    ("MapleStory Classic drops", "Safari"),               # macOS: the owner says it is a browser
    ("MapleStory Classic", "Discord"),
    ("Maple Helper - MapleStory Classic", ""),           # our own window
    ("Notepad", ""),
    ("", ""),
])
def test_not_the_game(title, app):
    assert not looks_like_game(title, app)
