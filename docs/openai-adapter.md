# OpenAI Agents SDK adapter

`OpenAIHandoffFilter` is currently tested with OpenAI Agents SDK 0.22.0 and
0.22.3. The package constrains compatibility to the 0.22.x line until a later
minor passes the integration suite.

## Send a compiled receiver view

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
