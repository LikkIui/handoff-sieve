"""Optional framework adapters."""

from handoff_sieve.adapters.langgraph import (
    LangGraphHandoff,
    compile_langgraph_state,
    langgraph_messages_to_history,
    langgraph_state_to_envelope,
)
from handoff_sieve.adapters.openai_agents import (
    OpenAIHandoffFilter,
    OpenAIHandoffPacketFilter,
)

__all__ = [
    "LangGraphHandoff",
    "OpenAIHandoffFilter",
    "OpenAIHandoffPacketFilter",
    "compile_langgraph_state",
    "langgraph_messages_to_history",
    "langgraph_state_to_envelope",
]
