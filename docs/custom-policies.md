# Custom policies

A policy subclasses `handoff_sieve.policies.base.Policy` and returns a processed
`HandoffEnvelope`.

```python
from handoff_sieve.models import HandoffEnvelope
from handoff_sieve.policies.base import Policy, PolicyContext


class KeepLastPolicy(Policy):
    name = "keep_last"
    version = "1"

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        output.messages = output.messages[-1:]
        context.report.add_event(self.name, "selected", count=len(output.messages))
        return output
```

Custom policies should follow four rules:

1. Copy the envelope before mutation.
2. Preserve messages whose `message.protected` value is true when deleting or
   summarizing content.
3. Put only counts, reason codes, stable IDs, and safe configuration metadata in
   audit events. Never store source content or matched secret values.
4. Raise a `HandoffSieveError` for an expected denial. The pipeline attaches the
   denied audit report. Unexpected exceptions are wrapped in
   `PolicyExecutionError` and remain available as `__cause__`.
5. Run every policy that can change receiver-visible content before egress
   redaction, and run every policy before the hard budget. HandoffSieve rejects a
   custom policy configured after either terminal gate.

Set a stable string `version` on the policy and change it when its audit-relevant
behavior changes. Events emitted during the policy call are stamped with that
version, and the version contributes to the pipeline configuration fingerprint.

HandoffSieve cannot infer what a custom policy does before the terminal gates.
Place it deliberately and add tests for secret absence, protected-content
retention, budget compliance, and deterministic output.

Private methods such as `_mark_protected`, `_replace_internal`, and
`_process_trusted_envelope` are reserved for HandoffSieve policies and reviewed
framework adapters. Public envelope processing strips caller-provided private
state.
