"""Links the app opens in the browser: only the sites it knows (the game database, its own releases).

The URLs come from data the app didn't write (the knowledge base's index, GitHub's API), so anything
else (another site, http://, file://, a custom scheme) is dropped without a word.
"""
from __future__ import annotations

import webbrowser
from urllib.parse import urlsplit

from .updater import APP_REPO

HOSTS = ("meowdb.com", "www.meowdb.com")


def safe_url(url) -> str | None:
    """The URL when it is https on meowdb.com or the app's own GitHub repository; else None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return None
    if u.scheme != "https" or not host:
        return None
    if host in HOSTS or (host == "github.com" and u.path.startswith(f"/{APP_REPO}/")):
        return url
    return None


def open_url(url) -> bool:
    """Open a known site in the browser; anything else is refused silently."""
    ok = safe_url(url)
    if ok:
        webbrowser.open(ok)
    return bool(ok)
