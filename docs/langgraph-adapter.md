# LangGraph adapter

The optional LangGraph adapter compiles one resolved graph-state snapshot into
the same `ReceiverContract` and `HandoffPacket` used by the framework-neutral
core and the OpenAI Agents SDK adapter.

## Install

```bash
python -m pip install "handoff-sieve[langgraph] @ https://github.com/LikkIui/handoff-sieve/releases/download/v0.3.0a3/handoff_sieve-0.3.0a3-py3-none-any.whl"
```

The supported compatibility window is LangGraph `>=1.0,<2`.
PyPI publication remains paused. The `0.3.0a3` release includes continuous
handoffs. To run repository examples, check out `v0.3.0a3` and install with
`python -m pip install -e ".[langgraph]"`.

In `0.3.0a3`, a resolved state containing a previous
`LangGraphHandoff` message can be compiled for the next agent. Its packet
sections and artifacts are inherited before new state is classified. The
message marker must agree with the packet, and its prior receiver must be the
current sender. The message is the source of this state; the optional
`handoff_packet` state key is not a second source that could duplicate it.
Explicit current state artifacts replace inherited artifacts with the same
name. State dropped by an earlier contract cannot be recovered later.

Canonical receiver JSON keeps every packet section but omits item fields equal
to public model defaults. `state["handoff_packet"]` already contains the full
public packet dictionary, including item defaults; consumers of message text
can use
`HandoffPacket.model_validate_json(message.content)` to restore defaults.
Non-default item state is retained. See the [migration notes](migration.md)
for the wire-format change and the offline 17.2% re-rendering comparison,
which does not measure provider-token or billing savings. The older `0.3.0a2`
and `0.3.0a1` wheels retain their original behavior.

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
