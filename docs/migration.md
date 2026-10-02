# Alpha migration notes

## `0.3.0a3`

Install the GitHub prerelease wheel or check out `v0.3.0a3` and install the
project in editable mode. PyPI publication remains paused; `0.3.0a2` and
`0.3.0a1` release files are unchanged.

- Canonical receiver JSON keeps the fixed top-level packet sections but omits
  item fields equal to public model defaults. Decode it with
  `HandoffPacket.model_validate_json()` to restore defaults. Non-default roles,
  kinds, tags, metadata, content, and artifact fields are preserved. Budgeting
  and adapters use that same canonical text.
- `HandoffPacket.to_envelope()` now explicitly assigns section kinds so that
  a packet can be compiled for a subsequent receiver. OpenAI and LangGraph
  contract adapters expand prior packet state, require the prior receiver to
  match the current sender, and let explicitly current artifacts replace
  inherited artifacts with the same name.
- `prepare_sender_state()` is an opt-in helper before compilation, using exact
  `metadata.task_id` and `metadata.state_key` identities. It never infers state
  updates from prose; applications that do not call it retain existing behavior.
- Normalization recognizes explicit multi-section dictionaries and Markdown
  headings after a preamble. Unknown dictionary keys and preambles remain
  unclassified. A source containing both recognized and unclassified content
  is counted in both report groups; indices remain original source positions.

If a consumer previously indexed every item field directly in `json.loads()`
output, switch to the public packet model to restore omitted defaults:

```python
from handoff_sieve import HandoffPacket

packet = HandoffPacket.model_validate_json(receiver_input)
message = packet.decisions[0]
print(message.role, message.kind, message.tags, message.metadata)
```

Default `Message.role="user"`, `kind="message"`, empty tags and metadata, and
default artifact fields can be absent from wire JSON. The typed models and
`packet.model_dump()` retain these fields. This does not change section names
or remove non-default item state.

Re-rendering the 20 saved checkpoint packets with this format preserves
identical typed state while reducing the local UTF-8 estimate from 8,177 to
6,773 handoff tokens (17.2%). Provider usage, billing, and downstream success
were not remeasured; the historical provider records remain unchanged.

`0.3.0a1` is the first public prerelease. Users of the earlier copied RelayGuard
prototype should review these changes before replacing it.

## `0.3.0a2`

- Compilation results add optional `budget: BudgetReport`. Compiler-generated
  results populate it; callers constructing results directly can omit it.
  Receiver-budget overflow errors add optional `BudgetExceededError.budget`;
  ordinary pipeline budget errors can leave it unset. Existing `report` semantics
  and error message prefixes are preserved.
- `required_tokens` includes the goal and canonical packet overhead at `stage`.
  `packet_tokens=None` means no receiver packet was emitted. Preferred omissions
  record budget decisions before and after processing; absent, unrequested, and
  policy-removed items are not counted as budget omissions. These local estimates
  are separate from provider-reported usage and are never added to packet JSON.
- `ContractError` adds optional `diagnostics` and `normalization` attributes.
  Missing-state errors keep their original message prefix and append readable
  hints. Inspect structured fields instead of matching the complete text.
- `ContractDiagnostics.stage` distinguishes incomplete `sender_state` from
  required state removed by a processing policy (`pipeline_output`). Counts
  describe that stage; diagnostics contain no source message content.
- `NormalizationReport.unclassified_message_indices` contains zero-based
  positions in the original envelope, before multi-section expansion. An
  empty tuple means none; `None` means no origin mapping is available. Custom
  normalizers can leave this new field unset. SDK positions refer to mapped
  task state, not raw SDK control items.
- Ambiguous classifications and other contract errors may have no diagnostics.
  `normalization` is attached only after normalization successfully completes;
  the existing optional audit `report` keeps its original meaning.

## Pipeline and configuration

- Route sets now deny unmatched and overlapping routes by default. Assign each
  route a stable `id`; configure `on_unmatched` or `on_multiple_match` only when
  a less strict behavior is intentional.
- Unknown message, artifact, and envelope fields are rejected. Caller input
  cannot set private protection or adapter reconstruction state.
- Use the order preserve, input redaction, schema, exact deduplication,
  selection or summarization, optional egress redaction, and hard budget.
- Add `RedactPolicy(..., stage="egress")` after a summarizer or custom transform
  that can generate new sensitive text. No policy may run after the hard
  budget.

## Failures and audit reports

- Expected denials raise a `HandoffSieveError` carrying `error.report`. Code that
  previously inspected exception text should use `failure_code`,
  `failed_policy`, and the versioned report fields.
- Audit reports do not include original handoff content. Provider token usage
  and HandoffSieve's local estimates use separate fields.
- Sender, receiver, and request identifiers are recorded as supplied. Replace
  customer names, email addresses, credentials, and message text with safe
  aliases before calling the pipeline.

## OpenAI Agents SDK adapter

- The supported Alpha window is `openai-agents>=0.22,<0.23`.
- The adapter treats history, pre-handoff items, and model input as one budgeted
  receiver view while leaving original session `new_items` unchanged.
- Server-managed hidden history, realtime streams, and partial snapshots are
  unsupported. Supply complete client-managed `HandoffInputData`.

## LangGraph adapter

- The supported alpha window is `langgraph>=1.0,<2`.
- Compile a resolved state snapshot with `compile_langgraph_state()`, then use
  `LangGraphHandoff(packet).command(...)` to replace the receiver message view.
- Tool calls must have matching results before compilation. Broken or pending
  pairs raise `HandoffIntegrityError`.

The unpublished prototype import `relayguard` was replaced by `handoff_sieve`.
No compatibility alias is shipped because the old coordinate was never a public
release. Update imports and editable installations before testing `0.3.0a1`.
