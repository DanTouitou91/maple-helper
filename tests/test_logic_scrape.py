"""The scraper keeps the page's own URL: the image download used to overwrite it."""
import json

import scrape_meowdb


def test_page_url_survives_the_image_download(tmp_path, monkeypatch):
    url = "https://meowdb.com/msclassic/monsters/5"
    ld = {"@type": "Thing", "name": "Red Snail", "image": "/img/5.png", "additionalProperty": [{"name": "Level", "value": 4}]}
    page = f'<script type="application/ld+json">{json.dumps(ld)}</script><h1>Red Snail</h1><p>Slow.</p>'
    fetched = []
    monkeypatch.setattr(scrape_meowdb, "fetch", lambda u, binary=False: fetched.append(u) or (None if binary else page))
    monkeypatch.setattr(scrape_meowdb, "KB", tmp_path)
    monkeypatch.setattr(scrape_meowdb, "DELAY_SECONDS", 0)
    monkeypatch.setitem(scrape_meowdb.LASTMOD, url, "2026-09-30")
    (tmp_path / "pages" / "monster").mkdir(parents=True)
    (tmp_path / "img" / "monster").mkdir(parents=True)
    e = scrape_meowdb.scrape_one("monster", "5", url, refresh=False)
    assert fetched == [url, "https://meowdb.com/img/5.png"]
    assert e["url"] == url and e["lastmod"] == "2026-09-30"
    front = (tmp_path / "pages" / "monster" / "5.md").read_text(encoding="utf-8").split("\n---")[0]
    assert json.loads(front.removeprefix("---\n"))["url"] == url
