# OpenAI Agents SDK adapter

`OpenAIHandoffFilter` is currently tested with OpenAI Agents SDK 0.22.0 and
0.22.3. The package constrains compatibility to the 0.22.x line until a later
minor passes the integration suite.

## Compile the current SDK history at handoff

`0.3.0a2` adds `OpenAIReceiverContractFilter`. Install the checkout with
`python -m pip install -e ".[openai]"`, or install the GitHub release wheel with
the `openai` extra. This API is not in the older `0.3.0a1` wheel.

```python
from agents import handoff
from handoff_sieve.adapters import OpenAIReceiverContractFilter

coder_handoff = handoff(
    agent=coder,
    input_filter=OpenAIReceiverContractFilter(
        receiver_contract,
        sender="researcher",
        receiver="coder",
    ),
)
```

Each invocation compiles that handoff's `input_history`, `pre_handoff_items`,
and `input_items` (or `new_items` when no replacement exists). Completed
function calls and outputs become one structured tool result with the call
ID, name, arguments, and output. Orphaned, duplicate, reused, or unfinished
calls raise `HandoffIntegrityError`.

The current SDK routing events and reasoning items are omitted from task
state. Text strings and input/output text blocks are supported. Images, audio,
other tool types, and server-managed state require an application-specific
mapper instead of being silently discarded. Local `run_context` is preserved
by identity and is never included in the packet.

Pass `artifacts=` for explicit application files or outputs, `pipeline=` for
optional cleanup, and `on_compile=` for a callback that receives the packet
and normalization report. `compile_openai_handoff(data, contract, sender=...,
receiver=...)` is also available for applications that own their filter logic.
The callback receives a fresh compilation per call; there is no shared latest
result that can leak between concurrent runs. A callback exception propagates.
The compilation's `budget` explains required size and preferred budget
omissions. It is available to `on_compile` and stays out of model-visible JSON.
Receiver-budget errors expose the same report as `BudgetExceededError.budget`.

One explicitly headed runtime message can contain several sections. Lines
after a heading stay with that section until the next heading; headings inside
fenced code are kept as text. Explicit kinds and tags still take precedence,
and conflicting metadata remains an error. The normalizer report counts input
messages, even when one message yields several section items.

Missing required state raises `ContractError` before the receiver is called.
Inspect `error.diagnostics` for missing sections, counts, and correction hints;
`error.normalization` records the completed local classification. Unclassified
positions refer to the mapped `HandoffEnvelope`, not raw SDK item positions:
routing items are omitted and completed tool pairs are combined. Correct the
source state explicitly and retry; the filter never invents missing facts.

See the [runnable SDK takeover example](../examples/openai_takeover/README.md).

## Send an already compiled receiver view

Compile the sender state first, then use `OpenAIHandoffPacketFilter` as the
handoff input filter:

```python
from agents import handoff
from handoff_sieve import compile_history
from handoff_sieve.adapters import OpenAIHandoffPacketFilter

compilation = compile_history(sender_state, receiver_contract)

coder_handoff = handoff(
    agent=coder,
    input_filter=OpenAIHandoffPacketFilter(compilation.packet),
)
```

The receiving agent sees one user item containing the packet's canonical JSON:
the goal, fixed packet sections, artifacts, and tool results. The filter does
not run the pipeline again and does not call a model. It removes the original
history and pre-handoff items from the receiver view while preserving the
SDK's original `new_items` for session history and preserving `run_context`.
Only complete, client-managed `HandoffInputData` snapshots are supported.

Use `OpenAIHandoffFilter` below when the SDK snapshot itself is the source that
the ordinary policy pipeline should process.

| SDK behavior | Status | HandoffSieve behavior |
|---|---|---|
| Client-managed `input_history` string or tuple | Supported | Included in one receiver-view envelope |
| `pre_handoff_items` | Supported | Included and restored to SDK `InputItem` values |
| `input_items` when supplied | Supported | Used as the receiving model input source |
| `new_items` fallback | Supported | Filtered copy goes to `input_items`; original `new_items` remains unchanged |
| Combined budget and exact deduplication | Supported | Applied once across all three segments |
| SDK control items | Supported for canonical 0.22.x types | Protected against removal; call/output type, order, and ID are validated after policies run |
| Shared adapter instance | Supported | Latest reports are context-local; thread isolation is tested |
| Server-managed conversation history | Unsupported | An exposed output whose call is hidden from the filter is denied; supply complete client-managed history |
| Realtime or streaming handoffs | Unsupported | Non-`HandoffInputData` shapes raise `UnsupportedAdapterModeError`; buffer a complete snapshot first |
| Async summarizer inside the sync filter | Unsupported | Denied with an audit report |

The adapter does not call a model. Its integration test uses real
`HandoffInputData`, `InputItem`, and `Agent` objects offline. `run_context` is
preserved by identity and is never placed in the model-visible envelope.
An additional offline `Runner` test drives a real handoff from one SDK `Agent`
to another with deterministic local `Model` implementations; it verifies that
the receiving model sees the filtered view without making a provider request.

`last_reports` is local to the current async/thread execution context. Use a
pipeline `CallbackReporter` or `JsonlReporter` when the report must be retained
after `Runner.run_sync` crosses back into the caller's context.

Control-item protection prevents HandoffSieve selection, deduplication,
summarization, and budget trimming from silently deleting an occurrence. A
final adapter invariant then verifies that every protected control occurrence
is still present and that recognized tool outputs have a preceding call with
the same type and ID. It also rejects ID changes, reordered relationships,
duplicate outputs, and missing IDs with a denied audit report.

The recognized 0.22.x pairs are function, computer, custom, local-shell,
shell, apply-patch, and MCP approval call/output forms. Unknown future SDK
control types remain protected, but they are not treated as a validated pair
until the compatibility window and test matrix are updated.
