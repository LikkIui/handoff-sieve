# LangGraph adapter

The optional LangGraph adapter compiles one resolved graph-state snapshot into
the same `ReceiverContract` and `HandoffPacket` used by the framework-neutral
core and the OpenAI Agents SDK adapter.

## Install

```bash
python -m pip install "handoff-sieve[langgraph]"
```

The supported compatibility window is LangGraph `>=1.0,<2`.

## Compile and route

```python
from handoff_sieve import ReceiverContract
from handoff_sieve.adapters import LangGraphHandoff, compile_langgraph_state

contract = ReceiverContract(
    goal="Implement the authentication module",
    required=("decisions", "pending_work"),
    preferred=("failed_attempts", "tool_results"),
    max_tokens=4_000,
)


def handoff_node(state):
    compilation = compile_langgraph_state(
        state,
        contract,
        sender="researcher",
        receiver="coder",
    )
    return LangGraphHandoff(compilation.packet).command("coder")
```

`compile_langgraph_state()` reads `state["messages"]` and, by default,
`state["artifacts"]`. The ordinary HandoffSieve normalizer then classifies the
history and the normal compiler enforces required sections and the token
budget. Custom state keys can be supplied through `messages_key` and
`artifacts_key`.

`LangGraphHandoff.command()` returns a real LangGraph `Command`. Its state
update removes the existing `messages` value through LangGraph's documented
remove-all control and adds one `HumanMessage` containing the canonical packet
JSON. It also writes the structured packet to `state["handoff_packet"]` so a
deterministic receiver node can consume it without reparsing message text. Set
`packet_key=None` when that extra state key is not part of the graph schema.

The graph's message state must use LangGraph's `add_messages` reducer, as
`MessagesState` does. For a command leaving a subgraph, pass LangGraph's parent
constant explicitly:

```python
from langgraph.types import Command

return LangGraphHandoff(packet).command(
    "coder",
    graph=Command.PARENT,
)
```

## Tool-call integrity

The adapter expects a resolved message-state snapshot. It pairs every
`AIMessage.tool_calls` entry with the matching `ToolMessage.tool_call_id` and
collapses the pair into one semantic `tool_results` item containing the call
identifier, tool name, arguments, and output. This retains useful completed
work without replaying an old tool invocation in the receiver graph.

An orphan result, reused call identifier, duplicate result, or unfinished call
raises `HandoffIntegrityError`. Compile the handoff after the tool node has
returned all results.

## Runnable example

```bash
python examples/langgraph_handoff/run.py
```

The example builds and invokes a real `StateGraph` locally. It makes no model
call and needs no API key. The receiver asserts that its `messages` state
contains exactly one canonical HandoffSieve packet.
