# Real SDK hybrid handoff diagnostic

The actual Agents SDK routed researcher → coder, composed a hybrid packet and
generated a Python module in **three real model requests**. The receiver HTTP
body contained one canonical `HandoffPacket`, without a previous response or
conversation continuation. The original sender state was unchanged.

The generated module passed **seven checks**: keyword-only API plus six renewal
behaviors. This is the existing synthetic session-policy fixture, not public
task success evidence or a head-to-head quality comparison.

Model alias: `gpt-5.6-sol`, endpoint `https://ckffai.com/v1`; underlying alias
identity is unverified. Requests and responses are retained without credential
headers. Retries were disabled. `report.json` contains packet size, actual usage,
the compilation plan and acceptance; the `call-*.json` files contain raw calls.

Reproduce with a compatible explicit model from the checkout:

```bash
python examples/receiver_goals/sdk_handoff.py --mode hybrid --model YOUR_MODEL --output outputs/hybrid-sdk
```

This result uses schema-bounded source IDs, section names and need indices.
The separate eight-task development run used the earlier line-range schema;
its schema failures stay in that run's denominator.
