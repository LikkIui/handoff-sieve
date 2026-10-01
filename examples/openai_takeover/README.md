# Compile the latest state at an actual SDK handoff

This example uses a real OpenAI Agents SDK `Runner`, a function tool, and a
researcher-to-coder handoff. The new APIs are included in `0.3.0a2`; the older
`0.3.0a1` wheel does not contain them.

From the repository checkout:

```bash
python -m pip install -e ".[openai]"
python examples/openai_takeover/run.py
```

The default run is offline. Both models are deterministic fixtures; no key,
provider request, or LLM success claim is involved.

The workflow runs in this order:

1. Researcher receives a compatibility constraint plus irrelevant notes.
2. The SDK executes `inspect_session_api` and stores its result.
3. Researcher emits one new message containing an accepted decision, a failed
   approach, and pending work, then invokes the handoff.
4. `OpenAIReceiverContractFilter` compiles the latest snapshot at this point.
5. Coder sees one canonical packet, generates a module, and passes the existing
   five checks plus a sixth check for the rejected expiry-before-reuse approach.

```text
Mapped sender state: 2,387 estimated tokens
Receiver packet: 322 estimated tokens
Receiver input items: 1
Provider calls: 0
Takeover acceptance: 6/6
```

These counts are the built-in UTF-8 estimate of mapped state and canonical
packet text, not provider prompt tokens. A headed runtime note is split into
sections; continuations and fenced code remain intact. No classifier model is
needed.

## Optional live coder

Set `OPENAI_API_KEY` in your process environment. A compatible provider can
also use `OPENAI_BASE_URL`. Supply its exact model name explicitly:

```bash
python examples/openai_takeover/run.py --live --model YOUR_MODEL --json
python examples/openai_takeover/run.py --live --model YOUR_MODEL --full-history --json
```

Each command makes one provider call. Researcher and the tool remain identical
deterministic fixtures so only the receiving context changes. The live coder
returns a small pure decision function, checked in a fresh workspace. Streaming,
automatic retries, tracing, and server-managed continuation are not enabled.

## Saved one-task checkpoint

The [verification record](checkpoint.json) includes both returned sources and
the original gateway usage. Requested model: `gpt-5.6-sol`; one trial per
condition through a maintainer-authorized compatible gateway.

| Condition | Receiver input items | Behavior checks | Gateway-reported input tokens |
|---|---:|---:|---:|
| Full History | 7 | 6/6 | 3,867 |
| HandoffSieve | 1 | 6/6 | 13,960 |

**The reported input usage is anomalous and its cause is unresolved.** Keep
these values as returned. This checkpoint confirms one task completion and a
smaller client context; it does not demonstrate provider-token or billing
savings and does not establish a general success rate.

A separate offline test exercises the actual SDK HTTP serializer with a
mocked response. Its request bodies are 10,060 / 1,985 bytes using a fixture
model name, with identical coder instructions. The packet request contains no
original history, tool replay, `previous_response_id`, or conversation ID.
This is a local serialization check, not a capture of the earlier live
requests or an explanation of the gateway's usage.

Run the focused integration tests:

```bash
python -m pip install -e ".[dev,openai]"
python -m pytest tests/test_openai_contract.py tests/test_openai_takeover_example.py
```

For an application-owned packet or custom state mapping, see the
[OpenAI adapter guide](../../docs/openai-adapter.md).
