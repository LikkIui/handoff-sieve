# A receiver brief with necessary original evidence

The optional hybrid path organizes the sender's state into a concise takeover
brief. It keeps exact code, constraints or failed output as original excerpts
only when their literal form is useful. This addresses a weakness in the earlier
extractive path: selecting faithful raw tool windows can still deliver duplicated
observations, operation JSON and more context than a strong summary.

```python
from openai import AsyncOpenAI
from handoff_sieve import ReceiverContract, compile_hybrid_handoff
from handoff_sieve.adapters import OpenAIHandoffComposer

async with AsyncOpenAI(max_retries=0, timeout=180) as client:
    result = await compile_hybrid_handoff(
        sender_state,
        ReceiverContract(
            goal="Implement the authentication module",
            needs=("Accepted compatibility constraints", "Unresolved work"),
            preferred=("constraints", "decisions", "pending_work", "evidence"),
            max_tokens=4000,
        ),
        composer=OpenAIHandoffComposer(client, model="YOUR_MODEL"),
    )
print(result.packet.to_receiver_text())
print(result.composer_usage)
```

Use `shared_source_available=True` only if the receiver can actually reread the
sender's source checkout. It lets the composer prefer useful file locations over
carrying implementations already available to the receiver. The default is
false. `material_target_tokens=1200` is a soft target; the complete canonical
packet, including the goal, metadata and escaping, must fit `max_tokens`.

One preparation call returns a `HybridPlan`:

- `brief`: statements grouped into requested packet sections, each with source
  references and the receiver needs it addresses;
- `excerpts`: source IDs and inclusive `start_line` / `end_line` coordinates in
  the original **message**, not repository line labels inside a tool response;
- `missing_needs`: needs the sender state cannot supply.

The program copies selected original lines, preserving whitespace, escaping and
line endings. The model does not retype them. Null bounds copy an entire value;
structured values and named artifacts must remain whole. Unknown sources, bad
or overlapping ranges, unsupported sections and uncovered needs fail explicitly.
The entire brief and essential excerpts are protected. Optional excerpts may be
omitted to fit the budget, without hidden rewriting, retries or fallback.

Statements distinguish source-reported observations from proposed next actions
and unverified hypotheses. `[Proposed]` and `[Unverified]` remain visible to the
receiver. A citation checks where a claim points; it **does not prove that the
claim follows from its source**. A model can still misinterpret the sender's
state. Existing cleanup may redact or transform content, with the existing audit
behavior; local copying guarantees apply before such configured transformations.

`result.plan` keeps the source references and selected ranges. Source IDs belong
to this compilation snapshot. `budget_omitted_excerpt_indices` and the hybrid
`omitted_count` count optional excerpts omitted for size, not deleted source
messages. `composer_usage` includes preparation cost. The provider sees the
supplied sender state, and total takeover cost can exceed that of a summary.

## OpenAI Agents SDK

```python
from agents import handoff
from handoff_sieve.adapters import OpenAIHybridHandoffFilter

transfer = handoff(
    coder,
    input_filter=OpenAIHybridHandoffFilter(
        contract,
        composer=composer,
        sender="researcher",
        receiver="coder",
    ),
)
```

The async filter reads the current SDK handoff snapshot and validates completed
tool pairs before calling the model. It forwards one canonical `HandoffPacket`
using the existing delivery adapter, while preserving the application snapshot.
Client-managed history is required, as with the existing filters.

Run the actual SDK demo, including seven receiver behavior/API checks:

```bash
python examples/receiver_goals/sdk_handoff.py --mode hybrid --model YOUR_MODEL --output outputs/hybrid-sdk
```

This uses a synthetic task and real model calls. It inspects the receiver's
actual HTTP body. It is not a general success-rate benchmark. Public-task
comparisons use frozen development states and retain earlier failures; see the
[source review](design-references-2026-10-11.md).
