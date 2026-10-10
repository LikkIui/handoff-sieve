# How HandoffSieve's selection rules work

The default path is a local, deterministic compiler. The caller describes the
receiver's needs; HandoffSieve recognizes explicit state categories, keeps the
requested state, checks the budget, and emits a typed packet. It does not call
a model to decide what the goal means.

## 1. Recognize explicit categories

`compile_handoff()` expects exact section names in `Message.kind` or tags.
`compile_history()` first uses `RuleBasedHistoryNormalizer` to recognize:

- exact category kinds/tags;
- dedicated `handoff_section` / `receiver_section` metadata;
- known structured keys such as `decisions` and `pending_work`;
- explicit headings such as `Decision:`, `Failed attempt:`, `TODO:`,
  `决定：`, and `待办：`;
- tool-role/kind results.

For example:

| Sender text | Recognized category |
|---|---|
| `Constraint: Preserve the public API.` | `constraints` |
| `Decision: Use SQLite.` | `decisions` |
| `Failed attempt: In-memory state was lost after restart.` | `failed_attempts` |
| `TODO: Implement persistent sessions.` | `pending_work` |
| `We compared several hosting providers.` | unclassified |

Explicit kind/tag classification takes precedence over inferred signals.
Conflicting recognized categories raise an error. Unrecognized conversation
is reported as unclassified and does not enter the default packet; it may
still contain important facts. Applications must label that state or provide
a custom normalizer. Headings are format rules, not semantic understanding.

## 2. Apply the receiver's contract

```python
ReceiverContract(
    goal="Implement persistent sessions",
    required=("constraints", "decisions", "failed_attempts", "pending_work"),
    preferred=("evidence", "tool_results"),
    max_tokens=1000,
)
```

Required sections must have items. Their entire content is included first;
if absent or larger than the budget, compilation fails with diagnostics.
Preferred sections are considered in declaration order and source order
within each section. A candidate that does not fit is skipped; smaller later
candidates can still fit. Unrequested categories are omitted.

The budget includes the rendered packet, goal, and structural overhead. It is
enforced with the configured local counter, not with a promise about the whole
provider prompt or bill. Cleanup transformations are followed by another
required/preferred budget check and a final count.

## 3. Optional state preparation

`prepare_sender_state()` is an explicit helper for already classified state:

- an exact `metadata.task_id` filter keeps the chosen task and unscoped shared
  state;
- within the same task, category, and `metadata.state_key`, the last state wins;
- completed work closes earlier pending work with the same key; later pending
  work can reopen it;
- exact public duplicates can be removed.

For ordinary text history, normalize before applying this helper. The current
SDK filter does not automatically apply task scoping or state-key folding.
Applications must explicitly compose the preparation path today.

## 4. SDK delivery

`OpenAIReceiverContractFilter` reads the latest SDK snapshot, including paired
completed function-tool results, and compiles a fresh packet. Its packet filter
supplies one canonical JSON message as receiver-visible history. The caller's
original state is copied rather than overwritten. LangGraph has a separate
adapter using the same core packet/contract concepts.

## What the current rules do not guarantee

- `goal` does not rank facts or infer missing decisions.
- Required checks validate category presence, not factual truth or semantic
  sufficiency; the audit also found empty-text placeholders can pass.
- Preferred order is FIFO, so early irrelevant evidence can displace later
  critical evidence. Receiver-specific item selection is a proposed feature,
  not yet a shipped capability.
- A later receiver cannot recover information omitted from an earlier packet.
  Applications should retain the full sender state for future views.
- These are not a mathematically minimal context search or a proof of task
  success. Downstream behavior needs separate validation.

The practical benefit is a reusable, inspectable contract/budget/packet path
that normally needs no extra model call or compression model. Stronger
summaries and framework-native filters can overlap with these capabilities;
no current result proves universal quality or speed superiority over them.

Implementation: [normalization](../src/handoff_sieve/normalization.py),
[compiler](../src/handoff_sieve/compiler.py),
[state preparation](../src/handoff_sieve/state.py), and
[SDK contract filter](../src/handoff_sieve/adapters/openai_contract.py).
