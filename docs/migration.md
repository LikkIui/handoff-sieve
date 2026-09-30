# Alpha migration notes

`0.3.0a1` is the first planned public prerelease. There is no previously
published HandoffSieve API to support, but users of the earlier copied
RelayGuard prototype should review these changes before replacing it.

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
