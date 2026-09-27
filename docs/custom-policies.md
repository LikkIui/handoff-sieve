# Custom policies

A policy subclasses `relayguard.policies.base.Policy` and returns a processed
`HandoffEnvelope`.

```python
from relayguard.models import HandoffEnvelope
from relayguard.policies.base import Policy, PolicyContext


class KeepLastPolicy(Policy):
    name = "keep_last"

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
4. Raise a `RelayGuardError` for an expected denial. The pipeline attaches the
   denied audit report. Unexpected exceptions are wrapped in
   `PolicyExecutionError` and remain available as `__cause__`.

Built-in order validation cannot infer whether a custom policy reads, removes,
or sends content. Place custom policies deliberately and add tests for secret
absence, protected-content retention, budget compliance, and deterministic
output.

Private methods such as `_mark_protected`, `_replace_internal`, and
`_process_trusted_envelope` are reserved for RelayGuard policies and reviewed
framework adapters. Public envelope processing strips caller-provided private
state.
