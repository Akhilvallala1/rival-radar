from langgraph.graph import END, START, StateGraph

from rival_radar.nodes.analyst import analyst
from rival_radar.nodes.notifier import notifier
from rival_radar.nodes.scraper import scraper
from rival_radar.nodes.writer import writer
from rival_radar.state import MonitorState

_builder = StateGraph(MonitorState)
_builder.add_node("scraper", scraper)
_builder.add_node("analyst", analyst)
_builder.add_node("writer", writer)
_builder.add_node("notifier", notifier)
_builder.add_edge(START, "scraper")
_builder.add_edge("scraper", "analyst")
_builder.add_edge("analyst", "writer")
_builder.add_edge("writer", "notifier")
_builder.add_edge("notifier", END)

app = _builder.compile()
