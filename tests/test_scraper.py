from rival_radar.nodes.scraper import compute_diff, compute_hash, strip_html


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
