from datetime import datetime

from langchain_anthropic import ChatAnthropic

from rival_radar.state import MonitorState

_llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=2048)

_SYSTEM = (
    "You are writing a weekly competitive intelligence Slack digest for a B2B SaaS product team. "
    "Format using Slack mrkdwn: *bold*, _italic_, bullet points with •, and relevant emoji. "
    "Structure:\n"
    "1. Header line: '🎯 *Rival Radar — Weekly Brief*' and the date\n"
    "2. One section per competitor with their key changes as bullets\n"
    "3. A '💡 *Key Takeaways*' section with 2-3 actionable bullets\n"
    "Keep it scannable. Aim for 150-250 words total."
)


def writer(state: MonitorState) -> dict:
    analyses = state.get("analyses", [])

    if not analyses:
        return {
            "brief": (
                "🎯 *Rival Radar — Weekly Brief*\n\n"
                "No significant competitor changes detected this week. "
                "All monitored pages are unchanged."
            )
        }

    today = datetime.utcnow().strftime("%B %d, %Y")
    user_msg = (
        f"Today's date is {today}. "
        "Write this week's competitive intelligence Slack digest based on these findings:\n\n"
        + "\n\n---\n\n".join(analyses)
    )
    response = _llm.invoke(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ]
    )
    brief = response.content if isinstance(response.content, str) else str(response.content)
    return {"brief": brief}
