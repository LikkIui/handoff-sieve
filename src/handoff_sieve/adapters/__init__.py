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
from handoff_sieve.adapters.openai_composer import OpenAIHandoffComposer
from handoff_sieve.adapters.openai_contract import (
    OpenAIHybridHandoffFilter,
    OpenAIModelHandoffFilter,
    OpenAIReceiverContractFilter,
    compile_openai_handoff,
)
from handoff_sieve.adapters.openai_selector import OpenAIHandoffSelector

__all__ = [
    "OpenAIHybridHandoffFilter",
    "OpenAIHandoffComposer",
    "LangGraphHandoff",
    "OpenAIHandoffFilter",
    "OpenAIHandoffPacketFilter",
    "OpenAIHandoffSelector",
    "OpenAIModelHandoffFilter",
    "OpenAIReceiverContractFilter",
    "compile_langgraph_state",
    "compile_openai_handoff",
    "langgraph_messages_to_history",
    "langgraph_state_to_envelope",
]
