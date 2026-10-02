"""Free Market prices: the site's JSON isn't ours, so an odd shape never raises out of a lookup."""
import io
import urllib.request

import pytest

from maplehelper import market

NORMAL = {"rows": [{"itemName": "Red Potion", "priceEach": 50, "createdAt": "2026-10-01T10:00:00Z"},
                   {"itemName": "Red Potion", "price": 70, "createdAt": 1759312000000},
                   {"itemName": "Red Potion Pouch", "priceEach": 9}]}
HOSTILE = {
    "top-level list": [1, 2],
    "rows not a list": {"rows": {"a": 1}},
    "rows null": {"rows": None},
    "row not a dict": {"rows": [1, "x", None]},
    "itemName not a string": {"rows": [{"itemName": 5, "priceEach": 1}]},
    "price inf (1e999 in JSON)": {"rows": [{"itemName": "Red Potion", "priceEach": float("inf")}]},
    "price nan": {"rows": [{"itemName": "Red Potion", "priceEach": float("nan")}]},
    "price huge int": {"rows": [{"itemName": "Red Potion", "priceEach": 10**40}]},
    "price bool": {"rows": [{"itemName": "Red Potion", "priceEach": True}]},
    "price negative": {"rows": [{"itemName": "Red Potion", "priceEach": -5}]},
    "createdAt odd": {"rows": [{"itemName": "Red Potion", "priceEach": 3, "createdAt": "yesterday"},
                               {"itemName": "Red Potion", "priceEach": 3, "createdAt": [1]},
                               {"itemName": "Red Potion", "priceEach": 3, "createdAt": float("inf")}]},
}


def test_normal_rows():
    m = market.summarize(NORMAL["rows"], "Red Potion")
    from datetime import datetime
    assert (m.count, m.median, m.low, m.high) == (2, 60, 50, 70)
    assert m.latest == datetime.fromisoformat("2026-10-01T10:00:00+00:00").timestamp()      # the newest report


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_hostile_rows_never_raise(name):
    data = HOSTILE[name]
    m = market.summarize(data.get("rows") if isinstance(data, dict) else data, "Red Potion")
    assert m.median is None or 0 < m.median < market.MAX_PRICE
    assert m.latest is None or m.latest < 1e14


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.mark.parametrize("body,expect", [(b"[1,2]", 0), (b'{"rows":[{"itemName":"Red Potion","priceEach":1e999}]}', 0),
                                         (b"<html>", None), (b'{"rows": null}', 0),
                                         (b'{"rows":[{"itemName":"Red Potion","priceEach":40}]}', 1)])
def test_free_market_never_raises(monkeypatch, body, expect):
    market._cache.clear()
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10: _Resp(body))
    m = market.free_market("Red Potion")
    assert (m.count if m else None) == expect
