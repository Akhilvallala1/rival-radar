import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime
from urllib.parse import urlparse

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from rival_radar.database import SessionLocal
from rival_radar.models import Snapshot
from rival_radar.state import DiffEntry, MonitorState

# Hostnames blocked before DNS resolution to keep SSRF tests fast and reliable.
_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal", "metadata.aws"})


def _check_ip_not_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, label: str) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(f"Address {label!r} is not a public address (SSRF protection)")


def validate_url_safe(url: str) -> None:
    """Reject non-HTTP(S) URLs and URLs that resolve to private/internal addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    if hostname.lower() in _BLOCKED_HOSTNAMES or hostname.endswith(".internal"):
        raise ValueError(f"Hostname {hostname!r} is blocked")

    # Fast-path: raw IP address supplied directly
    try:
        addr = ipaddress.ip_address(hostname)
        _check_ip_not_internal(addr, hostname)
        return
    except ValueError:
        pass  # Not a raw IP; fall through to DNS resolution

    try:
        results = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise ValueError(f"Could not resolve hostname {hostname!r}: {exc}") from exc
    for _af, _sock, _proto, _canon, sockaddr in results:
        addr_str = str(sockaddr[0])
        _check_ip_not_internal(ipaddress.ip_address(addr_str), addr_str)


def strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def compute_diff(old_text: str, new_text: str) -> dict:
    return {
        "changed": compute_hash(old_text) != compute_hash(new_text),
        "old_excerpt": old_text[:400],
        "new_excerpt": new_text[:400],
    }


def _is_feed_url(url: str) -> bool:
    return any(url.endswith(s) for s in ("/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml"))


def _is_g2_url(url: str) -> bool:
    return "g2.com/products/" in url and "/reviews" in url


def _extract_jsonld_g2(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "Product" and "aggregateRating" in data:
            agg = data["aggregateRating"]
            reviews_raw = data.get("review", [])[:3]
            return {
                "overall_rating": float(agg.get("ratingValue", 0)),
                "review_count": int(agg.get("reviewCount", 0)),
                "recent_reviews": [
                    {
                        "title": r.get("name", ""),
                        "snippet": r.get("reviewBody", "")[:200],
                    }
                    for r in reviews_raw
                ],
            }
    return {"overall_rating": None, "review_count": None, "recent_reviews": []}


def _parse_g2_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD is more stable than CSS selectors; try it first
    result = _extract_jsonld_g2(soup)
    if result["overall_rating"] is not None:
        return result

    # CSS selector fallback for pages without JSON-LD
    rating_el = soup.select_one("[data-testid='rating-stars'] + * .fw-semibold")
    overall_rating = None
    if rating_el:
        try:
            overall_rating = float(rating_el.text.strip())
        except ValueError:
            pass

    count_el = soup.select_one("[data-testid='reviews-count']")
    review_count = None
    if count_el:
        m = re.search(r"(\d[\d,]*)", count_el.text)
        if m:
            try:
                review_count = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

    review_cards = soup.select(".paper.paper--white.paper--box")[:3]
    recent_reviews = []
    for card in review_cards:
        title_el = card.select_one(".review-title, [itemprop='name']")
        body_el = card.select_one(".review-text, [itemprop='reviewBody']")
        recent_reviews.append({
            "title": title_el.get_text(strip=True) if title_el else "",
            "snippet": body_el.get_text(strip=True)[:200] if body_el else "",
        })

    return {
        "overall_rating": overall_rating,
        "review_count": review_count,
        "recent_reviews": recent_reviews,
    }


def _hash_g2_data(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _fetch_g2_page(url: str, session: aiohttp.ClientSession) -> dict:
    headers = {"User-Agent": "RivalRadar/0.1 (competitive-intelligence)"}
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), headers=headers) as resp:
        html = await resp.text(errors="replace")
    return _parse_g2_page(html)


async def _fetch_page(url: str, session: aiohttp.ClientSession) -> str:
    headers = {"User-Agent": "RivalRadar/0.1 (competitive-intelligence)"}
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), headers=headers) as resp:
        html = await resp.text(errors="replace")
        return strip_html(html)


def _fetch_feed(url: str) -> str:
    feed = feedparser.parse(url)
    entries = feed.entries[:5]
    parts = [f"{e.get('title', '')} — {e.get('summary', '')[:200]}" for e in entries]
    return "\n".join(parts)


async def _scrape_all(competitors: list) -> dict[str, DiffEntry]:
    diffs: dict[str, DiffEntry] = {}

    # Collect all competitor IDs for the batch prefetch.
    all_competitor_ids = [comp["competitor_id"] for comp in competitors]

    async with aiohttp.ClientSession() as http:
        with SessionLocal() as db:
            # --- Batch prefetch: ONE query instead of one per URL (N+1 → 2 queries) ---
            # For each (competitor_id, url) pair keep only the most-recent Snapshot.
            # We fetch all relevant snapshots ordered oldest→newest so that iterating
            # in order lets the last write for a key be the most-recent one.
            all_snapshots = (
                db.query(Snapshot)
                .filter(Snapshot.competitor_id.in_(all_competitor_ids))
                .order_by(Snapshot.scraped_at.asc())
                .all()
            )
            # Build a dict keyed by (competitor_id, url) → latest Snapshot
            prev_snapshot: dict[tuple, Snapshot] = {}
            for snap in all_snapshots:
                prev_snapshot[(snap.competitor_id, snap.url)] = snap

            # Accumulate new Snapshot objects; committed once at the end.
            new_snapshots: list[Snapshot] = []

            for comp in competitors:
                raw_urls = comp.get("urls", [])
                urls: list[str] = json.loads(raw_urls) if isinstance(raw_urls, str) else raw_urls
                for url in urls:
                    try:
                        validate_url_safe(url)
                        if _is_g2_url(url):
                            g2_data = await _fetch_g2_page(url, http)
                            new_hash = _hash_g2_data(g2_data)
                            new_text = json.dumps(g2_data)
                        elif _is_feed_url(url):
                            new_text = await asyncio.get_event_loop().run_in_executor(
                                None, _fetch_feed, url
                            )
                            new_hash = compute_hash(new_text)
                        else:
                            new_text = await _fetch_page(url, http)
                            new_hash = compute_hash(new_text)

                        # O(1) dict lookup — no per-URL DB query.
                        prev = prev_snapshot.get((comp["competitor_id"], url))
                        if prev is not None:
                            changed = prev.content_hash != new_hash
                            old_text = prev.text
                        else:
                            changed = True
                            old_text = ""

                        new_snapshots.append(
                            Snapshot(
                                competitor_id=comp["competitor_id"],
                                url=url,
                                content_hash=new_hash,
                                text=new_text[:8000],
                                scraped_at=datetime.utcnow(),
                            )
                        )
                        if _is_g2_url(url):
                            diffs[url] = DiffEntry(
                                competitor=comp["name"],
                                changed=changed,
                                old_excerpt=old_text,
                                new_excerpt=new_text,
                                source="g2",
                            )
                        else:
                            diffs[url] = DiffEntry(
                                competitor=comp["name"],
                                changed=changed,
                                old_excerpt=old_text[:400],
                                new_excerpt=new_text[:400],
                            )
                    except Exception as exc:
                        diffs[url] = DiffEntry(
                            competitor=comp["name"],
                            changed=False,
                            old_excerpt=f"error: {exc}",
                            new_excerpt="",
                        )

            # Single bulk insert + one commit for all new snapshots.
            if new_snapshots:
                db.add_all(new_snapshots)
                db.commit()

    return diffs


def scraper(state: MonitorState) -> dict:
    diffs = asyncio.run(_scrape_all(state["competitors"]))
    return {"diffs": diffs}
