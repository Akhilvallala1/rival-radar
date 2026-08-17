import pytest

from rival_radar.nodes.scraper import compute_diff, compute_hash, strip_html, validate_url_safe


def test_strip_html_removes_tags():
    assert "Hello" in strip_html("<h1>Hello</h1>")
    assert "<" not in strip_html("<p>World</p>")


def test_strip_html_removes_script_content():
    html = "<script>alert('xss')</script><p>Safe content</p>"
    result = strip_html(html)
    assert "alert" not in result
    assert "Safe content" in result


def test_strip_html_removes_style_content():
    html = "<style>.hidden { display: none }</style><p>Visible</p>"
    result = strip_html(html)
    assert "display" not in result
    assert "Visible" in result


def test_strip_html_collapses_whitespace():
    html = "<p>Hello</p>   <p>World</p>"
    result = strip_html(html)
    assert "  " not in result


def test_compute_hash_is_deterministic():
    assert compute_hash("hello") == compute_hash("hello")


def test_compute_hash_differs_for_different_input():
    assert compute_hash("hello") != compute_hash("world")


def test_compute_diff_detects_change():
    diff = compute_diff("old pricing: $99/month", "new pricing: $149/month")
    assert diff["changed"] is True
    assert diff["old_excerpt"] == "old pricing: $99/month"
    assert diff["new_excerpt"] == "new pricing: $149/month"


def test_compute_diff_no_change():
    diff = compute_diff("same content here", "same content here")
    assert diff["changed"] is False


def test_compute_diff_first_run_empty_old():
    diff = compute_diff("", "brand new content")
    assert diff["changed"] is True
    assert diff["old_excerpt"] == ""
    assert diff["new_excerpt"] == "brand new content"


def test_compute_diff_excerpt_truncated():
    long_text = "x" * 1000
    diff = compute_diff("", long_text)
    assert len(diff["new_excerpt"]) == 400


# ── SSRF / URL validation ─────────────────────────────────────────────────────


def test_validate_url_safe_accepts_public_https():
    validate_url_safe("https://example.com/pricing")


def test_validate_url_safe_accepts_public_http():
    validate_url_safe("http://example.com/pricing")


def test_validate_url_safe_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="http or https"):
        validate_url_safe("ftp://example.com/file.txt")


def test_validate_url_safe_rejects_file_scheme():
    with pytest.raises(ValueError, match="http or https"):
        validate_url_safe("file:///etc/passwd")


def test_validate_url_safe_rejects_localhost():
    with pytest.raises(ValueError):
        validate_url_safe("http://localhost/admin")


def test_validate_url_safe_rejects_loopback_ip():
    with pytest.raises(ValueError):
        validate_url_safe("http://127.0.0.1/")


def test_validate_url_safe_rejects_private_class_a():
    with pytest.raises(ValueError):
        validate_url_safe("http://10.0.0.1/")


def test_validate_url_safe_rejects_private_class_b():
    with pytest.raises(ValueError):
        validate_url_safe("http://172.16.0.1/")


def test_validate_url_safe_rejects_private_class_c():
    with pytest.raises(ValueError):
        validate_url_safe("http://192.168.1.1/")


def test_validate_url_safe_rejects_metadata_endpoint():
    with pytest.raises(ValueError):
        validate_url_safe("http://metadata.google.internal/computeMetadata/v1/")


def test_validate_url_safe_rejects_ipv6_loopback():
    with pytest.raises(ValueError):
        validate_url_safe("http://[::1]/")


def test_validate_url_safe_rejects_no_hostname():
    with pytest.raises(ValueError):
        validate_url_safe("http:///path")
