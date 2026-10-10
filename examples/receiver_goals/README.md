# Real receiver-goal selection and takeover

These examples use real model calls, not offline fixture agents. Install
`.[openai]` from the current checkout. Choose a model supporting Responses
structured outputs. Set `OPENAI_API_KEY` and optional `OPENAI_BASE_URL`, or enter
the credential at the non-echoing prompt. Credentials and HTTP authentication
headers are not written to result files.

```bash
python examples/receiver_goals/demo.py --model YOUR_MODEL --output outputs/receiver-goals
python examples/receiver_goals/sdk_handoff.py --model YOUR_MODEL --output outputs/receiver-sdk
python -m examples.receiver_goals.pilots --model YOUR_MODEL --output outputs/receiver-pilots
```

Each output directory must be new, preserving earlier runs and failures.

- `demo.py`: one synthetic sender state, a coder and reviewer, four conditions.
  Includes a stronger receiver-aware summary. Checks the generated module's API
  and six behaviors, plus three reviewer judgments. The model views must contain
  different original source IDs, not merely different goal labels.
- `sdk_handoff.py`: a live researcher routes to a coder using the real Agents
  SDK. The selector runs in the async handoff filter. The actual receiver HTTP
  body must contain one canonical packet with no server-side continuation.
- `pilots`: reuses the checkout's three public executable takeover tasks and
  existing host acceptance. Removes category labels for a disclosed diagnostic;
  content and public starter files remain unchanged. Compares full history,
  receiver-aware summary and model selection. This command requires a checkout
  because it reuses `evals.takeover` fixtures; it is not a wheel-only command.

Preparation calls count toward total usage. Automatic client retries are
disabled. Every completed raw response and provider error is retained. The
selector never receives grading expectations. Small synthetic task results
demonstrate mechanism and failure modes; they do not prove general superiority
or billing savings. See [model handoff](../../docs/model-handoff.md).
