# Researcher → coder → reviewer, entirely offline

Run two real OpenAI Agents SDK handoffs in one `Runner` execution:

```bash
python -m pip install -e ".[openai]"
python examples/three_agent_relay/run.py
```

All three models are deterministic local fixtures. The example needs no API
key, makes no provider request, and disables tracing. It verifies actual SDK
integration and executable task behavior; it does not measure LLM success.

The researcher supplies a stable keyword-only API, ordered refresh-action
rules, and a rejected approach: checking expiry before token reuse. Its first
`OpenAIReceiverContractFilter` sends one canonical packet to the coder and
omits unrelated launch notes.

The coder generates `solution/session_policy.py` from the packet's API and
rules. A real SDK function tool writes it to an isolated temporary workspace
and runs the existing five independent behavior checks. The completed tool
result contains the source read back from that file and its check results.
The coder then emits new completed-work and pending-work notes and hands off
to the reviewer through a second contract filter.

The reviewer receives one packet carrying the original constraints,
decisions, and failed approach together with the coder's new work and
completed tool result. It extracts the generated source from that result,
writes it to a fresh temporary workspace, and checks the actual module in a
separate process. Its nine checks cover the keyword-only API and all eight
boolean input combinations, including an expired revoked token. It does not
approve based only on the coder's reported test result.

The output reports source and packet token estimates for each handoff,
preserved state, coder acceptance `5/5`, reviewer acceptance `9/9`, and zero
provider calls. Counts use the configured local UTF-8 estimate and may change
when packet rendering changes. The second packet can be larger than the
first because it also carries generated code and completed-work evidence.
Temporary workspaces are removed after the run.

For a machine-readable record and the focused tests:

```bash
python examples/three_agent_relay/run.py --json
python -m pytest tests/test_three_agent_relay_example.py
```

The negative test restores the rejected expiry-before-reuse implementation.
The coder's existing five checks pass, but the reviewer's additional behavior
check rejects it. Packet-field assertions are boundary checks and are not
counted as task acceptance.
