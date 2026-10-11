# Corrective selector retest on the same ten development tasks

The initial source-only takeover run exposed two invalid extraction plans:
one invented a source ID, and another cited evidence absent from its selections.
Those failures remain in the original run. This separate real-API retest uses
the exact same frozen sender snapshots and receiver contracts.

The OpenAI backend now emits bounded catalog indices and attaches need indices
to each selected item. The application maps indices back to original source IDs
and derives coverage, keeping public packet and plan interfaces unchanged.
Semantic relevance and sufficiency remain model judgments.

All ten requests produced a locally valid packet within the original estimated
4,000-token limit, without an automatic retry. This measures reference/coverage
validation and budgeting, **not downstream task success**. It adds zero new
distinct tasks and is not an independent benchmark trial of the earlier code.
These ten calls reported 154,872 provider tokens; the mean rendered packet
estimate was 1,118 tokens. Smaller packets do not establish task sufficiency.

See `run-manifest.json` for the exact implementation revision and
`reproduce.py.txt` for the executed diagnostic. Each task retains the API request,
parsed response, provider usage, compilation and report. Credentials and
authentication headers are not recorded. The model name is the configured
gateway identifier; its underlying upstream identity is not independently verified.
