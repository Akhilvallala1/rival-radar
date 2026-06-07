from typing import TypedDict


class CompetitorEntry(TypedDict):
    competitor_id: int
    name: str
    urls: list[str]


class DiffEntry(TypedDict):
    competitor: str
    changed: bool
    old_excerpt: str
    new_excerpt: str


class MonitorState(TypedDict):
    competitors: list[CompetitorEntry]
    diffs: dict[str, DiffEntry]   # url → diff
    analyses: list[str]           # per-competitor LLM analysis
    brief: str                    # final Slack digest
    run_id: int
