from collections import defaultdict

from langchain_anthropic import ChatAnthropic

from rival_radar.state import MonitorState

_llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=1024)

_SYSTEM = (
    "You are a competitive intelligence analyst for a B2B SaaS company. "
    "Given changes detected on a competitor's web pages, write a concise 2-4 sentence analysis "
    "explaining what changed and what it signals strategically. "
    "Be specific. Focus on what matters to a product manager or founder."
)


def analyst(state: MonitorState) -> dict:
    diffs = state.get("diffs", {})

    by_competitor: dict[str, list[dict]] = defaultdict(list)
    for url, diff in diffs.items():
        if diff.get("changed"):
            by_competitor[diff["competitor"]].append(
                {
                    "url": url,
                    "old": diff.get("old_excerpt", ""),
                    "new": diff.get("new_excerpt", ""),
                }
            )

    analyses: list[str] = []
    for comp_name, changes in by_competitor.items():
        changes_text = "\n\n".join(
            f"URL: {c['url']}\nBefore: {c['old'][:300]}\nAfter:  {c['new'][:300]}"
            for c in changes
        )
        user_msg = f"Competitor: {comp_name}\n\nChanges detected this week:\n{changes_text}"
        response = _llm.invoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        text = response.content if isinstance(response.content, str) else str(response.content)
        analyses.append(f"*{comp_name}*\n{text}")

    return {"analyses": analyses}
