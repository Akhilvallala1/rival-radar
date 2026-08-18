# G2 Monitoring — Design Spec

## Overview

Extend the scraper pipeline to fetch and track G2 review data for each competitor. G2 page state (overall rating, review count, and the three most recent review titles/snippets) is hashed for change detection. Detected changes are injected into the analyst prompt as a dedicated G2 section.

---

## 1. G2 URL Pattern

G2 product pages follow a stable URL convention:

```
https://www.g2.com/products/{slug}/reviews
```

Where `{slug}` is the URL-safe product identifier used by G2, e.g. `salesforce-sales-cloud`, `hubspot-crm`.

**Storage:** The G2 slug (or full URL) is stored as one of the competitor's `urls` entries. The scraper uses `_is_g2_url()` to route it through the dedicated G2 fetcher instead of the generic HTML scraper.

```python
def _is_g2_url(url: str) -> bool:
    return "g2.com/products/" in url and "/reviews" in url
```

---

## 2. Data to Extract

From each G2 page, extract the following structured fields:

| Field            | Type            | Description                                      |
|------------------|-----------------|--------------------------------------------------|
| `overall_rating` | `float`         | Star rating shown in the aggregate score widget  |
| `review_count`   | `int`           | Total number of reviews displayed on the page   |
| `recent_reviews` | `list[dict]`    | The 3 most recently posted reviews              |

Each entry in `recent_reviews` contains:

```python
{
    "title":   str,   # review headline
    "snippet": str,   # first ~200 chars of the review body
}
```

### 2a. Scraping Approach — CSS Selectors (primary)

G2 renders product pages server-side, so `aiohttp` + `BeautifulSoup` is sufficient without a headless browser.

```python
from bs4 import BeautifulSoup

def _parse_g2_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Overall rating — displayed in the score widget
    # Selector targets the large numeric rating, e.g. "4.5"
    rating_el = soup.select_one("[data-testid='rating-stars'] + * .fw-semibold")
    # Fallback: look for itemprop="ratingValue" in JSON-LD (see 2b)
    overall_rating = float(rating_el.text.strip()) if rating_el else None

    # Review count — "Based on N reviews" text
    count_el = soup.select_one("[data-testid='reviews-count']")
    review_count = None
    if count_el:
        m = re.search(r"(\d[\d,]*)", count_el.text)
        review_count = int(m.group(1).replace(",", "")) if m else None

    # Three most recent reviews
    review_cards = soup.select(".paper.paper--white.paper--box")[:3]
    recent_reviews = []
    for card in review_cards:
        title_el  = card.select_one(".review-title, [itemprop='name']")
        body_el   = card.select_one(".review-text, [itemprop='reviewBody']")
        recent_reviews.append({
            "title":   title_el.get_text(strip=True)  if title_el  else "",
            "snippet": body_el.get_text(strip=True)[:200] if body_el else "",
        })

    return {
        "overall_rating": overall_rating,
        "review_count":   review_count,
        "recent_reviews": recent_reviews,
    }
```

**Note:** G2 periodically updates its markup. If the primary selectors break, fall back to the JSON-LD path (2b) before raising an error.

### 2b. Fallback — JSON-LD

G2 pages embed a `<script type="application/ld+json">` block conforming to `schema.org/Product`. Extract from it when CSS selectors yield `None`:

```python
import json as _json

def _extract_jsonld_g2(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(tag.string or "")
        except _json.JSONDecodeError:
            continue
        if data.get("@type") == "Product" and "aggregateRating" in data:
            agg = data["aggregateRating"]
            reviews_raw = data.get("review", [])[:3]
            return {
                "overall_rating": float(agg.get("ratingValue", 0)),
                "review_count":   int(agg.get("reviewCount", 0)),
                "recent_reviews": [
                    {
                        "title":   r.get("name", ""),
                        "snippet": r.get("reviewBody", "")[:200],
                    }
                    for r in reviews_raw
                ],
            }
    return {"overall_rating": None, "review_count": None, "recent_reviews": []}
```

---

## 3. Change Detection

Hash the extracted structured data (not the raw HTML) so that cosmetic page changes (ads, layout tweaks) do not trigger false positives.

```python
import hashlib, json

def _hash_g2_data(data: dict) -> str:
    """Stable, order-independent hash of extracted G2 fields."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
```

The resulting hash is stored as `Snapshot.content_hash` (same column used for regular pages). The `Snapshot.text` column stores the JSON-serialised `data` dict (capped at 8 000 chars to match the existing convention).

### Detection flow

```
prev_snapshot = most recent Snapshot for (competitor_id, g2_url)
new_data      = _parse_g2_page(html)          # structured dict
new_hash      = _hash_g2_data(new_data)

changed = (prev_snapshot is None) or (prev_snapshot.content_hash != new_hash)

if prev_snapshot:
    old_data = json.loads(prev_snapshot.text)
else:
    old_data = {}

DiffEntry(
    competitor   = comp["name"],
    changed      = changed,
    old_excerpt  = json.dumps(old_data),
    new_excerpt  = json.dumps(new_data),
    source       = "g2",              # new optional field — see note below
)
```

**`DiffEntry.source` field:** Add an optional `source: str = "web"` field to `DiffEntry` in `src/rival_radar/state.py`. G2 diffs carry `source="g2"`. This lets the analyst node route them to the dedicated G2 prompt section.

---

## 4. Analyst Prompt Integration

In `src/rival_radar/nodes/analyst.py`, after grouping diffs by competitor, separate G2 diffs from regular web diffs and append a dedicated G2 section to the user message.

### Updated `analyst` node logic

```python
def analyst(state: MonitorState) -> dict:
    diffs = state.get("diffs", {})

    by_competitor: dict[str, dict] = defaultdict(lambda: {"web": [], "g2": []})

    for url, diff in diffs.items():
        if diff.get("changed"):
            bucket = "g2" if diff.get("source") == "g2" else "web"
            by_competitor[diff["competitor"]][bucket].append(
                {"url": url, "old": diff.get("old_excerpt", ""), "new": diff.get("new_excerpt", "")}
            )

    analyses = []
    for comp_name, buckets in by_competitor.items():
        web_changes  = buckets["web"]
        g2_changes   = buckets["g2"]

        if not web_changes and not g2_changes:
            continue

        # --- existing web-change section ---
        web_text = "\n\n".join(
            f"URL: {c['url']}\nBefore: {c['old'][:300]}\nAfter:  {c['new'][:300]}"
            for c in web_changes
        ) if web_changes else "No website changes detected."

        # --- new G2 section ---
        g2_text = _format_g2_diff(g2_changes) if g2_changes else "No G2 changes detected."

        user_msg = (
            f"Competitor: {comp_name}\n\n"
            f"Website changes detected this week:\n{web_text}\n\n"
            f"G2 review page changes:\n{g2_text}"
        )
        # ... invoke LLM as before ...
```

### G2 diff formatter

```python
def _format_g2_diff(g2_changes: list[dict]) -> str:
    """Render old vs new G2 structured data into readable text for the LLM."""
    lines = []
    for c in g2_changes:
        try:
            old = json.loads(c["old"]) if c["old"] else {}
            new = json.loads(c["new"]) if c["new"] else {}
        except json.JSONDecodeError:
            old, new = {}, {}

        lines.append(
            f"Overall rating:  {old.get('overall_rating', 'N/A')} → {new.get('overall_rating', 'N/A')}\n"
            f"Review count:    {old.get('review_count', 'N/A')} → {new.get('review_count', 'N/A')}\n"
            f"Recent reviews (new):\n" +
            "\n".join(
                f"  • {r['title']}: {r['snippet']}"
                for r in new.get("recent_reviews", [])
            )
        )
    return "\n\n".join(lines)
```

### Prompt template addition (system prompt amendment)

Append the following sentence to `_SYSTEM` in `analyst.py`:

```
When G2 review data is present, note any rating changes (even 0.1 stars is significant at scale),
large swings in review volume, and recurring themes in the newest review snippets that signal
customer sentiment shifts.
```

---

## 5. Implementation Checklist

- [ ] Add `beautifulsoup4` to project dependencies (`pyproject.toml` / `requirements.txt`)
- [ ] Add `_is_g2_url()` helper to `nodes/scraper.py`
- [ ] Add `_parse_g2_page()` + `_extract_jsonld_g2()` to `nodes/scraper.py`
- [ ] Add `_hash_g2_data()` to `nodes/scraper.py` (replaces `compute_hash` for G2 paths)
- [ ] Add optional `source: str` field to `DiffEntry` in `state.py`
- [ ] Route G2 URLs in `_scrape_all()` to the new fetcher path
- [ ] Update `analyst.py` to separate and format G2 diffs
- [ ] Add G2 URL selector to the dashboard's "Add Competitor" form (UX hint, not enforced server-side)
