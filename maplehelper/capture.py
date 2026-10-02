"""Screen grabs shared by the Windows and macOS layers (both capture like any screenshot tool)."""
from __future__ import annotations

import io

import mss
from PIL import Image

MAX_SIDE = 1280
GAME_TITLES = ("maplestory classic", "maplestory", "classic world")
# a browser tab, video or chat about the game names it too ("MapleStory Classic drops - Google Chrome")
OTHER_APPS = ("google chrome", "chromium", "mozilla firefox", "firefox", "microsoft edge", "safari", "opera", "brave",
              "brave browser", "vivaldi", "arc", "discord", "youtube", "twitch")
OTHER_SUFFIXES = tuple(f"- {a}" for a in OTHER_APPS) + ("- mozilla firefox private browsing",)


def _plain(text: str) -> str:
    # Edge writes "Microsoft\u200bEdge"; Firefox separates with an em dash
    t = (text or "").lower().replace("\u200b", "").replace("—", "-").replace("–", "-")
    return " ".join(t.split())


def looks_like_game(title: str, app: str = "") -> bool:
    """The game's own window: its name in the title (or the app's name, when macOS hides titles),
    and not a browser, video or chat window that only talks about it."""
    t, a = _plain(title), _plain(app)
    names = f"{t} {a}"
    if "maple helper" in names or not any(g in names for g in GAME_TITLES):
        return False
    return not (a in OTHER_APPS or t in OTHER_APPS or t.endswith(OTHER_SUFFIXES) or t.startswith("discord |"))


def grab_image(x: int, y: int, w: int, h: int) -> Image.Image:
    """RGB capture of a screen rectangle, in mss coordinates (Windows: physical pixels, macOS: points)."""
    with mss.MSS() if hasattr(mss, "MSS") else mss.mss() as s:
        shot = s.grab({"left": x, "top": y, "width": max(1, w), "height": max(1, h)})
    return Image.frombytes("RGB", shot.size, shot.rgb)


def grab_jpeg(rect: tuple[int, int, int, int]) -> bytes:
    """JPEG of a screen rectangle (x, y, w, h), longest side 1280px."""
    img = grab_image(*rect)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
