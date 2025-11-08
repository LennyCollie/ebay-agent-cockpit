import json
import os
from services.kleinanzeigen import search_kleinanzeigen

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "kleinanzeigen_sample.html")

def test_parser_from_fixture(tmp_path, monkeypatch):
    # monkeypatch the _fetch to read the fixture so the test has no network dependency
    def _fake_fetch(url, timeout=15):
        with open(FIXTURE, "r", encoding="utf-8") as f:
            return f.read()

    # patch the private _fetch function inside the module
    import services.kleinanzeigen as k
    monkeypatch.setattr(k, "_fetch", _fake_fetch)

    items = search_kleinanzeigen("lego", per_page=5)
    assert isinstance(items, list)
    assert len(items) >= 1
    item = items[0]
    assert "id" in item and item["id"].startswith("kleinanzeigen:")
    assert "title" in item and isinstance(item["title"], str) and item["title"]
    assert "url" in item and item["url"].startswith("https://")
