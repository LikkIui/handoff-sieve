# Name review: HandoffSieve

Review date: 2026-09-28

This is a collision screen for an open-source Alpha, not a legal trademark
opinion. Public indexes can change between review and publication.

## Decision

Use these planned coordinates:

- project: **HandoffSieve**;
- PyPI distribution: `handoff-sieve`;
- Python import: `handoff_sieve`;
- repository: `handoff-sieve`.

“Sieve” describes the product's main job: retain the necessary parts of an
agent handoff while filtering, redacting, budgeting, and auditing the receiver
view. It is more specific to data minimization than a broad security claim such
as “firewall.”

## Why RelayGuard was rejected

- The exact GitHub organization name is already occupied:
  <https://github.com/RelayGuard>.
- An active AI incident-response project already uses the exact repository and
  product name and overlaps on guard and audit concepts:
  <https://github.com/prabhakaran-jm/relayguard>.
- Other unrelated products use RelayGuard for blockchain RPC protection,
  industrial alarms, IEC 61850 tooling, and delivery monitoring:
  <https://0xrelayguard.com/docs/security>, <https://relayguard.co.uk/>,
  <https://relayguard.de/en/home/>, and <https://relayguard.net/>.

An available PyPI spelling would not remove this broader project-name and
search-result collision.

## Alternatives screened

| Candidate | Result on 2026-09-28 | Decision |
|---|---|---|
| HandoffGuard | `handoff-guard` 0.2.1 already validates LLM agent boundaries: <https://pypi.org/project/handoff-guard/> | Reject |
| HandoffGate | PyPI spellings returned 404, but adjacent public repositories use `handoff-gate` | Lower rank |
| HandoffShield | PyPI spellings returned 404, but an adjacent `agent-handoff-shield` repository exists | Lower rank |
| AgentEgress | An adjacent AI agent/MCP egress security project already uses AgentEgress | Reject |
| HandoffFirewall | No indexed exact PyPI or GitHub project found; name is descriptive and makes a broader security claim | Reserve alternative |
| ContextSentry | No exact PyPI project found; “Sentry” is crowded and the name omits handoff | Reserve alternative |
| HandoffSieve | Both PyPI spellings returned 404; no exact public GitHub repository or organization was indexed | Selected |

PyPI treats hyphens, underscores, and periods as equivalent for normalized
project-name comparison. Both compact and hyphenated spellings were checked
where applicable.

## Publication gates

Immediately before any public action:

1. repeat the normalized PyPI and GitHub checks;
2. confirm the remote repository can be renamed to `handoff-sieve`;
3. review relevant company, domain, common-law, and applicable trademark
   registries with qualified counsel if the project will be commercialized;
4. update every repository URL and verify redirects;
5. reserve the PyPI coordinate only as part of the reviewed release process.

No PyPI project, domain, GitHub organization, or trademark has been registered
by this local decision.
