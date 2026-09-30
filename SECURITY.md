# Security policy

HandoffSieve is an alpha project. Its redaction policies are a defense-in-depth
measure, not a guarantee that every secret or piece of personal data will be
detected.

## Supported versions

Before the first public prerelease, only the current `main` branch receives
security fixes. After publication, this table will identify supported release
lines explicitly.

## Important limitations

- Built-in detectors are pattern based and can produce false positives or
  false negatives.
- Custom application secrets require custom patterns.
- Custom regex compilation, total scanned bytes/strings, and per-match runtime
  are bounded. A limit or timeout denies the handoff with an audit report.
- Run input redaction before a summarizer so source secrets do not reach it.
  Because a summarizer can generate a new matching secret, use an egress
  `RedactPolicy` after summarization and before the hard budget.
- Place every custom policy that can change receiver-visible content before
  egress redaction. HandoffSieve rejects policies configured after that terminal
  pass or after the hard budget.
- Audit reports intentionally store counts and policy names, not removed or
  redacted source text.
- Public input cannot set HandoffSieve's private `protected` or adapter state;
  unknown model fields are rejected.
- `PreservePolicy` trusts configured public tags and kinds. If an untrusted
  sender controls those labels, validate or replace them before the pipeline;
  otherwise it can force a fail-closed budget denial by marking excess content
  as important.
- Rule-based configurations reject unmatched sender/receiver routes by
  default. Use `on_unmatched: warn` or `pass` only after reviewing that path.
- OpenAI Agents SDK control items are protected from trimming, but redacting
  tool arguments or outputs may still change tool semantics.

Test policies with representative data before production use. Keep provider
authentication, authorization, and server-side data controls in place.

## Reporting a vulnerability

Do not open a public issue containing real credentials or private user data.
Use [GitHub private vulnerability reporting](https://github.com/LikkIui/handoff-sieve/security/advisories/new).
If that page is unavailable, open an issue containing only a request for a
private contact channel and no vulnerability details. Revoke any credential
that may have been exposed.

Include the affected version or commit, a minimal reproduction using synthetic
data, the expected security property, and the observed result. Do not attach
production prompts, audit logs, credentials, or personal data.

