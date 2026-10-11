# Model-assisted handoff: select original state for the next task

For a concise generated receiver brief with host-copied original evidence,
see [hybrid handoff](hybrid-handoff.md). This page describes the earlier
original-only extraction path, which remains available independently.

The opt-in model path reads ordinary, unlabeled history and selects original
text spans for the receiver's goal. It is designed for mixed task histories,
superseded decisions, failed approaches, and evidence that appears too late
for the deterministic FIFO budget rule.

```python
from openai import AsyncOpenAI
from handoff_sieve import ReceiverContract, compile_model_handoff
from handoff_sieve.adapters import OpenAIHandoffSelector

async with AsyncOpenAI(max_retries=0, timeout=180) as client:
    result = await compile_model_handoff(
        sender_state,
        ReceiverContract(
            goal="Fix session.py renewal behavior",
            required=("constraints", "artifacts"),
            preferred=("decisions", "failed_attempts", "pending_work", "tool_results"),
            needs=(
                "Latest accepted expiry and token reuse policy",
                "Failed approach and remaining implementation work",
                "Current source module to edit",
            ),
            max_tokens=1300,
        ),
        selector=OpenAIHandoffSelector(client, model="YOUR_MODEL"),
    )

print(result.packet.to_receiver_text())
print(result.selection.coverage)
print(result.selector_usage)
```

Use an explicit compatible model and endpoint supported by your client. The
backend uses Responses API structured outputs; it does not silently switch to
another model or an unconstrained summary. Install the existing `[openai]`
extra. No compression model, GPU, vector database, or extra service is needed.

## What changes from the rules path

1. The application supplies the receiver goal, requested sections, natural
   language `needs`, and final packet budget.
2. The compiler makes a catalog of original source units. Ordinary message
   text is split at nonblank lines; fenced code blocks stay together. Artifacts
   and structured message/tool values remain atomic. Source order stays visible.
   Tool reads with a `File: path (N lines)` header and consecutive numbered
   source lines use contiguous windows of at most 40 lines. Selecting a window
   also keeps its observed file header and enclosing blocks. This preserves
   available context; it never fetches or invents an unobserved declaration.
   Enclosure recognition is a best-effort indentation heuristic for single-line
   headers, not dependency analysis; multiline declarations may be missed.
   Host-only character offsets and indices are retained locally but omitted
   from the selector payload; nonempty task hints and metadata remain visible.
   The OpenAI payload shares repeated message metadata across its units.
   Before selection, the compiler counts the empty canonical packet, including
   the complete goal, and exposes the remaining source budget. Each unit has a
   conservative isolated insertion estimate that includes JSON, references,
   and observed context. Shared context and merging can reduce those estimates;
   they are planning hints, especially with custom/BPE counters. The final
   rendered packet remains the budget authority. If the goal and empty packet
   alone exceed the budget, compilation stops before any selector call.
3. One selector call returns source IDs, categories, essential flags, ranked
   optional selections, and source references covering each need. It does not
   generate the task facts or edit the sender's code. The OpenAI backend's
   wire format uses bounded catalog indices and places need indices on each
   selected item; the application maps them to original source IDs and derives
   coverage. This avoids separately citing evidence absent from the selection.
4. The application validates the plan, reconstructs content from its original
   snapshot, preserves essential/need-covered items, and fits optional items
   into the actual rendered packet budget. Unknown IDs, missing coverage,
   absent required sections, and essential overflow fail explicitly.
   A window and its context fit together or are omitted together. Adjacent
   selected spans in the same section are merged in original source order;
   `handoff_sieve.source_ids` retains their individual references. Automatically
   retained context appears in `selection.context_source_ids`.
5. The existing cleanup pipeline and packet adapters deliver that packet.
   Every fitted item is protected from destructive cleanup. Redaction or
   caller-supplied transforms can still modify its content and are reported.

This path applies `required` to the model-selected content in that section;
it does not preserve the entire original section. The deterministic
`compile_handoff()` and `compile_history()` retain their original whole-section
behavior. They reject nonempty `needs` because they cannot assess natural
language coverage. Use the model API when you request this capability.

## SDK handoff

```python
from agents import handoff
from handoff_sieve.adapters import OpenAIModelHandoffFilter

transfer = handoff(
    coder,
    input_filter=OpenAIModelHandoffFilter(
        contract,
        selector=selector,
        sender="researcher",
        receiver="coder",
    ),
)
```

The async filter reads the latest SDK snapshot and completed function-tool
results, calls the selector, and forwards one canonical packet. Keep using
client-managed history; the existing SDK server-managed-history limitations
still apply. The model selector receives the full supplied catalog: reducing
the next agent's context does not mean hiding that state from the selector's
provider. The original application state is preserved for later receivers.

## A live example with a stronger comparison

```bash
python examples/receiver_goals/demo.py \
  --model YOUR_MODEL \
  --output outputs/receiver-goals
```

Set `OPENAI_API_KEY` and, for a compatible gateway, `OPENAI_BASE_URL`; otherwise
the example asks for a credential without echoing it. It calls real models for
both packet preparation and takeover. The same sender state goes to a coder
and a reviewer under four conditions:

- Full history;
- the existing deterministic rule path;
- a receiver-aware model summary with the same goal, needs, and budget;
- model-assisted original-span selection.

The coder writes an actual module and is checked for its API and six behaviors.
The reviewer assesses the unchanged original module against three observations.
Every request, raw response, failure, reported usage, and preparation call is
saved. This is a small synthetic mechanism demo, not a general success estimate.
The two receiver views must retain different source-ID sets; merely changing
their goal text or rearranging the same facts does not count as a different view.

For an actual researcher → coder SDK handoff using real models at every stage:

```bash
python examples/receiver_goals/sdk_handoff.py \
  --model YOUR_MODEL \
  --output outputs/receiver-goals-sdk
```

This records the actual HTTP request body at the receiver boundary, checks that
it contains one canonical packet and no server-side history continuation, and
checks the generated module's API plus six behaviors. It normally makes three
requests: routing, selection, and coding. No local fixture model is substituted.

## Boundaries

- Source checks guarantee that selected facts were copied, not that the source
  is correct, current, or semantically sufficient. Need coverage is a model
  judgment. Validate the downstream task separately.
- The selector costs a model call and sees the full catalog. Total end-to-end
  tokens or latency can increase even when receiver context drops sharply.
- An enormous line, code block, artifact, or structured tool result stays
  atomic; this release does not truncate it or recursively summarize it.
- A bad or incomplete selector response fails; there is no hidden retry or
  full-history fallback. Configure retry explicitly on your own client.
- `omitted_count` in model compilation counts source units, not original
  messages. `selection` gives the exact retained and omitted unit IDs.
- Source IDs refer to this compilation snapshot, not a permanent memory store.
  Keep the original state if another receiver needs a different view.
