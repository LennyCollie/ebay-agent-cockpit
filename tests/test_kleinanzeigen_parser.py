# tests/test_kleinanzeigen_parser.py
"""
Unit tests for Kleinanzeigen parser using static HTML fixture.
"""
import os
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

# Import functions to test
from services.kleinanzeigen import _extract_items, _parse_item


@pytest.fixture
def sample_html():
    """Load the sample HTML fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "kleinanzeigen_sample.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def sample_soup(sample_html):
    """Parse the sample HTML into BeautifulSoup object."""
    return BeautifulSoup(sample_html, "lxml")


def test_extract_items_returns_list(sample_soup):
    """Test that _extract_items returns a list."""
    items = _extract_items(sample_soup, max_results=10)
    assert isinstance(items, list)


def test_extract_items_finds_articles(sample_soup):
    """Test that _extract_items finds the expected number of items."""
    items = _extract_items(sample_soup, max_results=10)
    assert len(items) >= 3, "Should find at least 3 valid items from fixture"


def test_extract_items_respects_max_results(sample_soup):
    """Test that _extract_items respects max_results parameter."""
    items = _extract_items(sample_soup, max_results=2)
    assert len(items) <= 2, "Should not return more than max_results"


def test_first_item_has_required_keys(sample_soup):
    """Test that the first parsed item has all required keys."""
    items = _extract_items(sample_soup, max_results=10)
    assert len(items) > 0, "Should have at least one item"
    
    first_item = items[0]
    required_keys = ["id", "title", "price", "currency", "url", "img", "source"]
    
    for key in required_keys:
        assert key in first_item, f"Item should have '{key}' key"


def test_first_item_values(sample_soup):
    """Test that the first item has expected values."""
    items = _extract_items(sample_soup, max_results=10)
    assert len(items) > 0, "Should have at least one item"
    
    first_item = items[0]
    
    # Check ID format
    assert first_item["id"].startswith("kleinanzeigen:"), "ID should be prefixed with 'kleinanzeigen:'"
    assert "2345678901" in first_item["id"], "ID should contain the data-adid value"
    
    # Check title
    assert first_item["title"] == "Gaming Laptop RTX 3060", "Title should match"
    
    # Check price (899 € should parse to "899.0")
    assert first_item["price"] is not None, "Price should be parsed"
    assert float(first_item["price"]) == 899.0, "Price should be 899.0"
    
    # Check currency
    assert first_item["currency"] == "EUR", "Currency should be EUR"
    
    # Check URL
    assert first_item["url"] is not None, "URL should be present"
    assert "kleinanzeigen.de" in first_item["url"], "URL should contain kleinanzeigen.de"
    assert "2345678901" in first_item["url"], "URL should contain the ad ID"
    
    # Check image
    assert first_item["img"] is not None, "Image should be present"
    assert first_item["img"].startswith("https://"), "Image should be a full URL"
    
    # Check source
    assert first_item["source"] == "kleinanzeigen", "Source should be 'kleinanzeigen'"


def test_second_item_decimal_price(sample_soup):
    """Test that decimal prices are correctly parsed."""
    items = _extract_items(sample_soup, max_results=10)
    assert len(items) >= 2, "Should have at least two items"
    
    second_item = items[1]
    
    # MacBook Pro with price "1.299 €" should parse to "1299.0"
    assert second_item["title"] == "MacBook Pro 2020 13\"", "Second item title should match"
    assert second_item["price"] is not None, "Second item should have price"
    assert float(second_item["price"]) == 1299.0, "Price should be 1299.0"


def test_vb_price_handling(sample_soup):
    """Test that VB (negotiable) prices are handled correctly."""
    items = _extract_items(sample_soup, max_results=10)
    
    # Find the ThinkPad item with VB price
    thinkpad_items = [item for item in items if "ThinkPad" in item["title"]]
    assert len(thinkpad_items) > 0, "Should find ThinkPad item"
    
    thinkpad = thinkpad_items[0]
    # VB should result in None price (not a numeric value)
    assert thinkpad["price"] is None, "VB price should be None"


def test_free_item_handling(sample_soup):
    """Test that 'Zu verschenken' (free) items are handled correctly."""
    items = _extract_items(sample_soup, max_results=10)
    
    # Find the free item
    free_items = [item for item in items if "defekt" in item["title"].lower()]
    assert len(free_items) > 0, "Should find free item"
    
    free_item = free_items[0]
    assert free_item["price"] is None, "Free item should have None price"


def test_lazy_loaded_image_handling(sample_soup):
    """Test that data-src images (lazy loading) are handled correctly."""
    items = _extract_items(sample_soup, max_results=10)
    
    # Find item with lazy-loaded image
    free_items = [item for item in items if "defekt" in item["title"].lower()]
    assert len(free_items) > 0, "Should find item with data-src image"
    
    free_item = free_items[0]
    assert free_item["img"] is not None, "Should have image URL"
    assert free_item["img"].startswith("https://"), "data-src should be converted to full URL"


def test_parse_item_returns_none_without_required_fields():
    """Test that _parse_item returns None when required fields are missing."""
    from bs4 import BeautifulSoup
    
    # Create a minimal article without required fields
    html = '<article class="aditem"></article>'
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    
    result = _parse_item(article)
    assert result is None, "Should return None when required fields are missing"


def test_parse_item_with_minimal_valid_data():
    """Test that _parse_item works with minimal valid data."""
    from bs4 import BeautifulSoup
    
    # Create a minimal but valid article
    html = '''
    <article class="aditem" data-adid="123456">
        <a href="/s-anzeige/test/123456" class="ellipsis">Test Title</a>
    </article>
    '''
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    
    result = _parse_item(article)
    assert result is not None, "Should return a result with minimal valid data"
    assert result["id"] == "kleinanzeigen:123456", "Should have correct ID"
    assert result["title"] == "Test Title", "Should have correct title"


def test_decimal_price_comma_format(sample_soup):
    """Test that prices with comma decimal separator are parsed correctly."""
    items = _extract_items(sample_soup, max_results=10)
    
    # Find Dell XPS item with "1.499,99 €"
    dell_items = [item for item in items if "Dell XPS" in item["title"]]
    assert len(dell_items) > 0, "Should find Dell XPS item"
    
    dell = dell_items[0]
    assert dell["price"] is not None, "Dell item should have price"
    # "1.499,99" should parse to 1499.99
    assert float(dell["price"]) == 1499.99, "Price with comma should parse correctly"


def test_all_items_have_source_kleinanzeigen(sample_soup):
    """Test that all items have source='kleinanzeigen'."""
    items = _extract_items(sample_soup, max_results=10)
    
    for item in items:
        assert item["source"] == "kleinanzeigen", f"Item {item['id']} should have source='kleinanzeigen'"


def test_all_items_have_unique_ids(sample_soup):
    """Test that all items have unique IDs."""
    items = _extract_items(sample_soup, max_results=10)
    
    ids = [item["id"] for item in items]
    unique_ids = set(ids)
    
    assert len(ids) == len(unique_ids), "All item IDs should be unique"
