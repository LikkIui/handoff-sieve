# Security policy

RelayGuard is an alpha project. Its redaction policies are a defense-in-depth
measure, not a guarantee that every secret or piece of personal data will be
detected.

## Important limitations

- Built-in detectors are pattern based and can produce false positives or
  false negatives.
- Custom application secrets require custom patterns.
- Summarizers can reproduce sensitive input unless redaction runs first.
- Audit reports intentionally store counts and policy names, not removed or
  redacted source text.
- OpenAI Agents SDK control items are protected from trimming, but redacting
  tool arguments or outputs may still change tool semantics.

Test policies with representative data before production use. Keep provider
authentication, authorization, and server-side data controls in place.

## Reporting a vulnerability

Do not open a public issue containing real credentials or private user data.
Use the repository owner's private security reporting channel once one is
configured. Revoke any credential that may have been exposed.

