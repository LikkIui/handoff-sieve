# Code references behind the model-assisted handoff path

Reviewed on 2026-10-10. These are implementation references, not claims of
head-to-head performance superiority. The new code is written for this
repository; no external implementation is vendored or copied.

| Project and inspected code | What the implementation does well | What HandoffSieve adopts |
|---|---|---|
| [agent-handoff: compress.ts](https://github.com/dabit3/agent-handoff/blob/master/src/compress.ts), `compressRelevance`, `scoreRelevance`, `summarizeMessages` | Scores messages using focus-term matches, recency, role, and length; reserves separate summary and raw-message budgets. Its summary is local pattern extraction, not an LLM. | Select for the receiver's goal before spending packet budget. Use a model to move beyond literal term matches and category FIFO. Keep a stronger receiver-aware summary as a comparison. |
| [agent-handoff-protocol: hybrid-compressor.ts](https://github.com/reaatech/agent-handoff-protocol/blob/4edb996f80412f2fc1108e4bb98be76fc50f8aba/packages/compression/src/hybrid-compressor.ts), `compress`, `extractKeyFacts`, `identifyOpenItems` | Separates summary, facts, entities, intents and open work; includes source-message IDs for facts. Extraction uses local patterns and fixed caps. | Keep structured task state and source-addressable facts rather than treating one prose summary as the whole handoff. Model-selected source units can express decisions, failed attempts and pending work from ordinary text. |
| [LLMLingua: prompt_compressor.py](https://github.com/microsoft/LLMLingua/blob/main/llmlingua/prompt_compressor.py), `compress_json`, sentence selection and `get_compressed_input` | Combines structured segmentation, ranking and compression; preservation flags force selected content to survive token filtering. Uses local neural models. | Separate indispensable content from optional context. Need-backed source units are pinned before local budgeting. We do not add its neural runtime or claim its published compression results. |
| [RTK: pytest_cmd.rs](https://github.com/rtk-ai/rtk/blob/a4cddfc5ce6e6412c66e9729c4200792d822a964/src/cmds/python/pytest_cmd.rs), `filter_pytest_output`, `run` | Parses output states, retains failures and expected/unexpected failure reports, and falls back to raw output when a failing run was not understood. | Preserve actual failure evidence, retain original state for inspection, and fail explicitly when selection cannot meet requirements. Do not claim a large structured tool log was safely compressed when it was merely dropped. |
| [LangChain handoff context engineering](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs#context-engineering) and existing installed SDK adapters | Separates transferred state from internal history and preserves tool-call/result validity. | Reuse the existing boundary and tool-pair handling; add model selection to that boundary instead of building another orchestrator. |

## Concrete product change

The deterministic path remains useful for already labeled state. The new
`compile_model_handoff()` handles mixed ordinary history, takes natural-language
receiver needs, obtains an original-source extraction plan from a model, and
checks references and the final packet locally. `OpenAIModelHandoffFilter`
integrates it into the existing SDK handoff.

The model supplies judgments about relevance and need coverage. The application
supplies the task text by copying original spans. This prevents the selector
from rewriting numeric policies, API names or code while making the receiver
view sensitive to the actual takeover goal.

This is a functional improvement over this repository's previous rules path,
not a new compression algorithm or a demonstrated win over every project.
The live demo compares full state, the previous rules path, a stronger
receiver-aware summary, and the new path under the same task checks. Preparation
cost and failed cases must stay visible. The next improvement should be driven
by those failures; more adapters or platform features remain out of scope.
