"""Unit tests for the production Kleinanzeigen article parser."""

from pathlib import Path

from bs4 import BeautifulSoup

from services.kleinanzeigen import (
    _extract_price,
    _parse_html_article,
    check_dependencies,
)


class TestKleinanzeigenParser:
    @classmethod
    def setup_class(cls):
        fixture_path = Path(__file__).parent / "fixtures" / "kleinanzeigen_sample.html"
        html_content = fixture_path.read_text(encoding="utf-8")
        cls.soup = BeautifulSoup(html_content, "lxml")
        cls.articles = cls.soup.select("article.aditem")

    @staticmethod
    def parse(article):
        return _parse_html_article(article, query="iphone")

    def test_fixture_loaded(self):
        assert len(self.articles) == 3

    def test_dependencies_available(self):
        assert check_dependencies()

    def test_parse_article_current_production_format(self):
        result = self.parse(self.articles[0])
        assert result is not None
        assert {
            "id", "item_id", "title", "price", "url", "image_url", "img",
            "location", "postal_code", "condition", "description",
            "published_date", "source", "src", "term",
        }.issubset(result)
        assert result["id"] == result["item_id"] == "ka_2345678901"
        assert result["title"] == "iPhone 13 128GB Blau"
        assert result["price"] == 599.0
        assert result["url"].startswith("https://www.kleinanzeigen.de/s-anzeige/")
        assert result["image_url"].startswith("https://img.kleinanzeigen.de/")
        assert result["img"] == result["image_url"]
        assert result["source"] == result["src"] == "kleinanzeigen"
        assert result["term"] == "iphone"

    def test_parse_multiple_articles(self):
        results = [self.parse(article) for article in self.articles]
        assert all(result is not None for result in results)
        assert len({result["item_id"] for result in results}) == 3

    def test_parse_free_offer(self):
        assert self.parse(self.articles[2])["price"] == 0.0

    def test_extract_price_current_numeric_format(self):
        cases = (
            ("599 EUR", 599.0),
            ("1.234 EUR", 1234.0),
            ("1.234,56 EUR", 1234.56),
            ("VB 500 EUR", 500.0),
        )
        for value, expected in cases:
            assert _extract_price(value) == expected

    def test_extract_price_free_text_is_not_numeric(self):
        assert _extract_price("Zu verschenken") is None
        assert _extract_price("") is None
