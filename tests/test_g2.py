"""Tests for G2 review page scraping helpers."""
from bs4 import BeautifulSoup

from rival_radar.nodes.scraper import (
    _extract_jsonld_g2,
    _hash_g2_data,
    _is_g2_url,
    _parse_g2_page,
)

_G2_HTML_WITH_JSONLD = """
<html><body>
<script type="application/ld+json">
{
    "@type": "Product",
    "aggregateRating": {"ratingValue": "4.5", "reviewCount": "200"},
    "review": [
        {"name": "Great tool", "reviewBody": "Really helpful for sales teams everywhere."},
        {"name": "Good value", "reviewBody": "Worth every penny for our team."}
    ]
}
</script>
</body></html>
"""

_G2_HTML_NO_JSONLD = """
<html><body>
<div data-testid="rating-stars">
  <span><span class="fw-semibold">4.3</span></span>
</div>
<div data-testid="reviews-count">Based on 150 reviews</div>
</body></html>
"""


# ── _is_g2_url ────────────────────────────────────────────────────────────────

def test_is_g2_url_review_page():
    assert _is_g2_url("https://www.g2.com/products/hubspot-crm/reviews") is True


def test_is_g2_url_regular_page():
    assert _is_g2_url("https://hubspot.com/pricing") is False


def test_is_g2_url_g2_non_review():
    assert _is_g2_url("https://www.g2.com/products/hubspot-crm/features") is False


def test_is_g2_url_g2_homepage():
    assert _is_g2_url("https://www.g2.com") is False


# ── _hash_g2_data ─────────────────────────────────────────────────────────────

def test_hash_g2_data_deterministic():
    data = {"overall_rating": 4.5, "review_count": 100, "recent_reviews": []}
    assert _hash_g2_data(data) == _hash_g2_data(data)


def test_hash_g2_data_changes_on_rating_update():
    old = {"overall_rating": 4.5, "review_count": 100, "recent_reviews": []}
    new = {"overall_rating": 4.6, "review_count": 100, "recent_reviews": []}
    assert _hash_g2_data(old) != _hash_g2_data(new)


def test_hash_g2_data_changes_on_review_count():
    old = {"overall_rating": 4.5, "review_count": 100, "recent_reviews": []}
    new = {"overall_rating": 4.5, "review_count": 101, "recent_reviews": []}
    assert _hash_g2_data(old) != _hash_g2_data(new)


def test_hash_g2_data_returns_64_char_hex():
    data = {"overall_rating": None, "review_count": None, "recent_reviews": []}
    result = _hash_g2_data(data)
    assert len(result) == 64
    int(result, 16)  # validates it's a valid hex string


# ── _extract_jsonld_g2 ────────────────────────────────────────────────────────

def test_extract_jsonld_parses_rating_and_count():
    soup = BeautifulSoup(_G2_HTML_WITH_JSONLD, "html.parser")
    result = _extract_jsonld_g2(soup)
    assert result["overall_rating"] == 4.5
    assert result["review_count"] == 200


def test_extract_jsonld_parses_recent_reviews():
    soup = BeautifulSoup(_G2_HTML_WITH_JSONLD, "html.parser")
    result = _extract_jsonld_g2(soup)
    assert len(result["recent_reviews"]) == 2
    assert result["recent_reviews"][0]["title"] == "Great tool"
    assert "sales teams" in result["recent_reviews"][0]["snippet"]


def test_extract_jsonld_missing_product_returns_none():
    html = "<html><body><script type='application/ld+json'>{}</script></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    result = _extract_jsonld_g2(soup)
    assert result["overall_rating"] is None
    assert result["review_count"] is None
    assert result["recent_reviews"] == []


def test_extract_jsonld_no_script_tag():
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    result = _extract_jsonld_g2(soup)
    assert result["overall_rating"] is None


def test_extract_jsonld_malformed_json_skipped():
    html = "<html><body><script type='application/ld+json'>not-json</script></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    result = _extract_jsonld_g2(soup)
    assert result["overall_rating"] is None


# ── _parse_g2_page ────────────────────────────────────────────────────────────

def test_parse_g2_page_returns_required_keys():
    result = _parse_g2_page(_G2_HTML_WITH_JSONLD)
    assert "overall_rating" in result
    assert "review_count" in result
    assert "recent_reviews" in result


def test_parse_g2_page_uses_jsonld_when_available():
    result = _parse_g2_page(_G2_HTML_WITH_JSONLD)
    assert result["overall_rating"] == 4.5
    assert result["review_count"] == 200


def test_parse_g2_page_empty_html_returns_nones():
    result = _parse_g2_page("<html><body></body></html>")
    assert result["overall_rating"] is None
    assert result["review_count"] is None
    assert result["recent_reviews"] == []
