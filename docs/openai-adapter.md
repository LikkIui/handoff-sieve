# OpenAI Agents SDK adapter

`OpenAIHandoffFilter` is currently tested with OpenAI Agents SDK 0.22.0 and
0.22.3. The package constrains compatibility to the 0.22.x line until a later
minor passes the integration suite.

| SDK behavior | Status | RelayGuard behavior |
|---|---|---|
| Client-managed `input_history` string or tuple | Supported | Included in one receiver-view envelope |
| `pre_handoff_items` | Supported | Included and restored to SDK `InputItem` values |
| `input_items` when supplied | Supported | Used as the receiving model input source |
| `new_items` fallback | Supported | Filtered copy goes to `input_items`; original `new_items` remains unchanged |
| Combined budget and exact deduplication | Supported | Applied once across all three segments |
| SDK control items | Supported with limits | Marked protected against removal; redaction can still change arguments or output |
| Shared adapter instance | Supported | Latest reports are context-local; thread isolation is tested |
| Server-managed conversation history | Unsupported | Do not rely on this filter for history the SDK does not expose to it |
| Realtime or streaming handoffs | Unsupported | Buffer to a complete supported handoff before processing |
| Async summarizer inside the sync filter | Unsupported | Denied with an audit report |

The adapter does not call a model. Its integration test uses real
`HandoffInputData`, `InputItem`, and `Agent` objects offline. `run_context` is
preserved by identity and is never placed in the model-visible envelope.

Control-item protection prevents RelayGuard selection, deduplication,
summarization, and budget trimming from silently deleting an occurrence. It is
not a general validator for every possible tool-call graph. Applications should
test tool call/output pairing with their own item types before production use.
