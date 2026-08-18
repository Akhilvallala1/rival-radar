from typing import NotRequired, TypedDict


class CompetitorEntry(TypedDict):
    competitor_id: int
    name: str
    urls: list[str]


class DiffEntry(TypedDict):
    competitor: str
    changed: bool
    old_excerpt: str
    new_excerpt: str
    source: NotRequired[str]  # "web" (default) or "g2"


class MonitorState(TypedDict):
    competitors: list[CompetitorEntry]
    diffs: dict[str, DiffEntry]   # url → diff
    analyses: list[str]           # per-competitor LLM analysis
    brief: str                    # final Slack digest
    run_id: int
