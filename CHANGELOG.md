# Changelog

All notable changes to this project are documented in this file. Version
identifiers follow PEP 440 and the file follows the Keep a Changelog structure.
Until `1.0`, an alpha release can make incompatible API changes when its
changelog and migration notes explain them.

## [Unreleased]

### Added

- `ReceiverContract`, `HandoffPacket`, and deterministic `compile_handoff()`
  for building budgeted, receiver-specific task takeover context.
- `compile_history()` and `RuleBasedHistoryNormalizer` for turning ordinary
  headings, structured keys, metadata hints, and tool outputs into an
  inspectable receiver-specific packet without a model call.
- Canonical packet rendering and an `OpenAIHandoffPacketFilter` that sends the
  compiled receiver view directly through OpenAI Agents SDK handoffs.
- Three offline takeover demos with measured before/after context:
  researcher-to-coder, planner-to-executor, and researcher-to-reviewer.
- A packet-only researcher-to-coder boundary check with a deterministic offline
  receiver and five objective acceptance checks.
- A three-condition takeover evaluation scaffold with auditable payloads,
  deterministic grading, provider usage records, and an explicit-only OpenAI
  pilot runner.
- Three runnable takeover pilot fixtures: composite-cursor implementation,
  streaming CSV plan execution, and behavior-derived cursor-patch review.
- An explicit-only runnable provider runner for all three route pilots. Every
  condition gets the same starter and task prefix; strict source/review outputs
  are checked in fresh time-bounded processes, with handoff/input tokens,
  provider usage, events, failures, raw outputs, and behavior-derived review
  blockers recorded.
- The first controlled three-pilot provider checkpoint, with exact JSONL
  records and a machine-readable aggregate. HandoffSieve matched Full History
  at 3/3 successes while reducing handoff and measured provider tokens; the
  small single-trial sample is explicitly labelled as preliminary.
- A data-driven 20-task runnable takeover suite spanning seven coder, seven
  executor, and six reviewer tasks. The 17 new fixtures use executable hidden
  checks, host-only reference implementations, and the same three-condition
  provider runner as the original pilots.
- The complete single-trial 20-task provider checkpoint. HandoffSieve matched
  Full History at 18/20 successes while reducing handoff tokens by 45.6% and
  measured provider tokens by 25.0%; exact failures, provider timeouts, and
  validator corrections remain auditable in the checked-in records.
- A LangGraph adapter that compiles resolved message state with the same
  `ReceiverContract`, preserves completed tool-call/result meaning as one
  structured item, rejects broken pairs, and routes a packet-only receiver
  view through a real `Command`.
- A runnable offline LangGraph `StateGraph` example that verifies the receiver
  sees exactly one canonical packet message.

### Changed

- Renamed the unpublished RelayGuard prototype to HandoffSieve. The planned
  coordinates are distribution `handoff-sieve`, import `handoff_sieve`, and
  repository `handoff-sieve`.
- Refocused the product roadmap on context and handoff optimization through
  v0.3; enterprise security and cross-organization protocol work is future-only.

## [0.3.0a1] - Unreleased

The first planned public prerelease. It includes the original policy pipeline
and the complete v0.1–v0.3 receiver-specific handoff path described above.

## [0.2.0a1] - Not released

This internal candidate introduced the receiver-specific compilation API. It
was superseded before publication by `0.3.0a1`.

## [0.1.0a1] - Not released

### Added

- A framework-neutral handoff envelope and synchronous policy pipeline.
- Preserve, redaction, schema, exact-deduplication, selection, summarization,
  and hard-budget policies.
- Fail-closed YAML routing with stable rule identifiers and overlap handling.
- Versioned success and denial audit reports with JSONL and callback reporters.
- An OpenAI Agents SDK 0.22.x input-filter adapter with control-item and tool-pair
  integrity checks.
- A deterministic offline benchmark, downstream writer assertions, and an
  executable Failure Zoo.
- Typed package metadata and support for Python 3.10 through 3.13.

### Security

- Canonical public fields share one redaction, counting, and audit boundary.
- Caller input cannot set private protection or adapter reconstruction state.
- Regex, scan-volume, route, policy-order, and protected-budget failures deny
  the handoff with an audit report.
- Egress redaction prevents a summarizer or custom transform from bypassing the
  final secret scan.

[Unreleased]: https://github.com/LikkIui/handoff-sieve/compare/v0.3.0a1...HEAD
[0.3.0a1]: https://github.com/LikkIui/handoff-sieve/releases/tag/v0.3.0a1
[0.2.0a1]: https://github.com/LikkIui/handoff-sieve/releases/tag/v0.2.0a1
[0.1.0a1]: https://github.com/LikkIui/handoff-sieve/releases/tag/v0.1.0a1
