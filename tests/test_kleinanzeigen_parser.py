# tests/test_kleinanzeigen_parser.py
"""
Unit tests for Kleinanzeigen parser.

These tests use a fixture HTML file and don't require internet connectivity.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path so we can import services
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pytest
    from bs4 import BeautifulSoup
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    print("Warning: pytest not installed. Using simple assertions instead.")

from services.kleinanzeigen import (
    _parse_article,
    _extract_price,
    _safe_get_text,
    _safe_get_attr,
    check_dependencies
)


class TestKleinanzeigenParser:
    """Test suite for Kleinanzeigen parser functions."""
    
    @classmethod
    def setup_class(cls):
        """Load fixture HTML once for all tests."""
        fixture_path = Path(__file__).parent / "fixtures" / "kleinanzeigen_sample.html"
        
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")
        
        with open(fixture_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        cls.soup = BeautifulSoup(html_content, "lxml")
        cls.articles = cls.soup.select("article.aditem")
    
    def test_fixture_loaded(self):
        """Test that fixture HTML is loaded correctly."""
        assert self.soup is not None, "Soup should be initialized"
        assert len(self.articles) > 0, "Should find at least one article"
        assert len(self.articles) == 3, "Fixture should have exactly 3 articles"
    
    def test_dependencies_available(self):
        """Test that required dependencies are available."""
        assert check_dependencies(), "Dependencies (requests, bs4, lxml) should be available"
    
    def test_parse_article_basic(self):
        """Test basic article parsing."""
        if len(self.articles) == 0:
            pytest.skip("No articles in fixture")
        
        # Parse first article
        article = self.articles[0]
        result = _parse_article(article)
        
        assert result is not None, "Should parse article successfully"
        assert isinstance(result, dict), "Result should be a dictionary"
    
    def test_parse_article_required_keys(self):
        """Test that parsed article has all required keys."""
        if len(self.articles) == 0:
            pytest.skip("No articles in fixture")
        
        article = self.articles[0]
        result = _parse_article(article)
        
        required_keys = ["id", "title", "price", "currency", "url", "img", "source"]
        for key in required_keys:
            assert key in result, f"Result should have '{key}' key"
    
    def test_parse_article_id_format(self):
        """Test that ID has correct format."""
        article = self.articles[0]
        result = _parse_article(article)
        
        assert result["id"].startswith("kleinanzeigen:"), "ID should be prefixed with 'kleinanzeigen:'"
        assert len(result["id"]) > len("kleinanzeigen:"), "ID should have content after prefix"
    
    def test_parse_article_title(self):
        """Test title extraction."""
        article = self.articles[0]
        result = _parse_article(article)
        
        assert result["title"], "Title should not be empty"
        assert isinstance(result["title"], str), "Title should be string"
        assert "iPhone" in result["title"], "Title should contain 'iPhone'"
    
    def test_parse_article_url(self):
        """Test URL extraction and normalization."""
        article = self.articles[0]
        result = _parse_article(article)
        
        assert result["url"], "URL should not be empty"
        assert result["url"].startswith("https://"), "URL should be absolute (https://)"
        assert "kleinanzeigen.de" in result["url"], "URL should be kleinanzeigen.de domain"
    
    def test_parse_article_price_numeric(self):
        """Test price extraction for numeric prices."""
        article = self.articles[0]
        result = _parse_article(article)
        
        # First article should have price "599 €"
        assert result["price"] is not None, "Price should not be None"
        assert isinstance(result["price"], str), "Price should be string"
        # Price should be normalized (e.g., "599.00" or "599")
        try:
            float(result["price"])
        except ValueError:
            pytest.fail("Price should be parseable as float")
    
    def test_parse_article_price_free(self):
        """Test price extraction for free items."""
        if len(self.articles) < 3:
            pytest.skip("Need at least 3 articles in fixture")
        
        # Third article has "Zu verschenken"
        article = self.articles[2]
        result = _parse_article(article)
        
        # Free items should have price "0" or None
        assert result["price"] in ["0", "0.00", None], \
            "Free item should have price '0' or None"
    
    def test_parse_article_currency(self):
        """Test currency is always EUR."""
        article = self.articles[0]
        result = _parse_article(article)
        
        assert result["currency"] == "EUR", "Currency should always be EUR"
    
    def test_parse_article_source(self):
        """Test source is always kleinanzeigen."""
        article = self.articles[0]
        result = _parse_article(article)
        
        assert result["source"] == "kleinanzeigen", "Source should be 'kleinanzeigen'"
    
    def test_parse_article_image(self):
        """Test image URL extraction."""
        article = self.articles[0]
        result = _parse_article(article)
        
        # Image should either be a valid URL or None
        if result["img"]:
            assert result["img"].startswith("https://"), \
                "Image URL should be absolute (https://)"
    
    def test_parse_multiple_articles(self):
        """Test parsing all articles in fixture."""
        results = []
        for article in self.articles:
            result = _parse_article(article)
            if result:
                results.append(result)
        
        assert len(results) >= 1, "Should parse at least one article"
        assert len(results) <= len(self.articles), \
            "Should not return more results than articles"
    
    def test_extract_price_numeric(self):
        """Test price extraction from various formats."""
        test_cases = [
            ("599 €", "599.00"),
            ("1.234 €", "1234.00"),
            ("1.234,56 €", "1234.56"),
            ("VB 500 €", "500.00"),
        ]
        
        for input_str, expected in test_cases:
            result = _extract_price(input_str)
            assert result is not None, f"Should extract price from '{input_str}'"
            # Compare as floats for robustness
            assert float(result) == float(expected), \
                f"Price from '{input_str}' should be {expected}, got {result}"
    
    def test_extract_price_free(self):
        """Test price extraction for free items."""
        test_cases = [
            "Zu verschenken",
            "kostenlos",
            "",
        ]
        
        for input_str in test_cases:
            result = _extract_price(input_str)
            assert result in ["0", "0.00", None], \
                f"Free item '{input_str}' should return '0' or None, got {result}"
    
    def test_safe_get_text(self):
        """Test safe text extraction."""
        article = self.articles[0]
        
        # Should work with valid selector
        result = _safe_get_text(article, "a.ellipsis")
        assert isinstance(result, str), "Should return string"
        
        # Should return default with invalid selector
        result = _safe_get_text(article, "nonexistent.selector", default="DEFAULT")
        assert result == "DEFAULT", "Should return default for invalid selector"
    
    def test_safe_get_attr(self):
        """Test safe attribute extraction."""
        article = self.articles[0]
        
        # Should work with valid selector and attribute
        result = _safe_get_attr(article, "a.ellipsis", "href")
        assert isinstance(result, str), "Should return string"
        assert len(result) > 0, "Should return non-empty href"
        
        # Should return default with invalid selector
        result = _safe_get_attr(article, "nonexistent", "href", default="DEFAULT")
        assert result == "DEFAULT", "Should return default for invalid selector"


def run_tests():
    """Run tests without pytest."""
    print("Running Kleinanzeigen parser tests...\n")
    
    test_suite = TestKleinanzeigenParser()
    test_suite.setup_class()
    
    # Get all test methods
    test_methods = [
        method for method in dir(test_suite)
        if method.startswith("test_") and callable(getattr(test_suite, method))
    ]
    
    passed = 0
    failed = 0
    
    for method_name in test_methods:
        try:
            method = getattr(test_suite, method_name)
            method()
            print(f"✓ {method_name}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {method_name}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {method_name}: Unexpected error: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")
    
    return failed == 0


if __name__ == "__main__":
    if PYTEST_AVAILABLE:
        # Run with pytest if available
        pytest.main([__file__, "-v"])
    else:
        # Run simple test runner
        success = run_tests()
        sys.exit(0 if success else 1)
