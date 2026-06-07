import asyncio
import hashlib
import json
import re
from datetime import datetime

import aiohttp
import feedparser

from rival_radar.database import SessionLocal
from rival_radar.models import Snapshot
from rival_radar.state import DiffEntry, MonitorState


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
    async with aiohttp.ClientSession() as http:
        with SessionLocal() as db:
            for comp in competitors:
                raw_urls = comp.get("urls", [])
                urls: list[str] = json.loads(raw_urls) if isinstance(raw_urls, str) else raw_urls
                for url in urls:
                    try:
                        if _is_feed_url(url):
                            new_text = await asyncio.get_event_loop().run_in_executor(
                                None, _fetch_feed, url
                            )
                        else:
                            new_text = await _fetch_page(url, http)

                        new_hash = compute_hash(new_text)
                        prev = (
                            db.query(Snapshot)
                            .filter_by(competitor_id=comp["competitor_id"], url=url)
                            .order_by(Snapshot.scraped_at.desc())
                            .first()
                        )
                        old_text = prev.text if prev else ""
                        diff = compute_diff(old_text, new_text)

                        db.add(
                            Snapshot(
                                competitor_id=comp["competitor_id"],
                                url=url,
                                content_hash=new_hash,
                                text=new_text[:8000],
                                scraped_at=datetime.utcnow(),
                            )
                        )
                        db.commit()
                        diffs[url] = DiffEntry(
                            competitor=comp["name"],
                            changed=diff["changed"],
                            old_excerpt=diff["old_excerpt"],
                            new_excerpt=diff["new_excerpt"],
                        )
                    except Exception as exc:
                        diffs[url] = DiffEntry(
                            competitor=comp["name"],
                            changed=False,
                            old_excerpt=f"error: {exc}",
                            new_excerpt="",
                        )
    return diffs


def scraper(state: MonitorState) -> dict:
    diffs = asyncio.run(_scrape_all(state["competitors"]))
    return {"diffs": diffs}
