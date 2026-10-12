# Test feedback for the receiver

HandoffSieve supplies the receiver's context. An execution agent still needs to
read source, make changes and observe what actually happens. The earlier portable
source-only comparison could submit broken Python without ever seeing a test
error. It is retained as a separate development result.

The optional evaluation bridge now runs the original, unmodified
[mini-swe-agent DefaultAgent](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py)
at a fixed commit, checking its source SHA-256 before use. Its Model and
Environment protocols connect native Responses function calls, local bounded
source operations and condition-specific original-test observations. This uses
the real upstream controller, **not its default unrestricted Bash environment**.
It adds no dependency or adapter to the HandoffSieve core.

```text
HandoffPacket -> mini receiver -> edit -> original tests
                     ^                       |
                     +----- actual output ---+
```

## Execution boundary

The model client and all complete API records stay on the host. The public test
worker receives only a candidate patch and a frozen original-test request. It
has no model credential, sender history, encrypted reasoning, mounted host files,
grader imports or evaluator test patch. Each test uses a new container restored
to the public initial commit, plus an unchanged-source control.

The original suites are fixed before model generation: Django `forms_tests`
(680 tests) and two Sphinx autodoc modules (67 tests). The first environment
preflight failed due to ASCII filesystem encoding and newer docutils; the
separate corrected preflight passes without dropping tests. All conditions use
C.UTF-8 and Sphinx uses docutils 0.16, supported by the base checkout's tox.ini.
See [preflight metrics](../evals/public_swe/results/2026-10-12-mini-visible-preflight-v2/summary.json).

Each receiver gets at most 24 model calls, including finish, and two test
execution requests. Test calls share the receiver's step budget; there is no
hidden automatic retry. Original tests and fixtures are protected from editing.
Invalid test parameters return an actual tool error without executing a command
or consuming a test request. At least one test attempt is required before finish.
Source/test failures remain visible; a failed original suite is not silently
replaced with a passing subset.

## Optional usage

From the repository checkout, install the existing OpenAI extra and the pinned
upstream package separately:

```bash
python -m pip install -e ".[openai]"
python -m pip install "mini-swe-agent @ https://github.com/SWE-agent/mini-swe-agent/archive/04d809ceab9df28f9adaed044884180159172930.zip"
```

Supply your compatible client and a real test callback. The callback receives
the current patch bytes and returns a verified exit status and bounded output:

```python
from pathlib import Path
from evals.public_swe.mini_receiver import (
    MiniReceiverEnvironment,
    MiniReceiverModel,
    run_mini_receiver,
)

model = MiniReceiverModel(client, "YOUR_MODEL", Path("outputs/mini/calls"))
environment = MiniReceiverEnvironment(checkout, run_original_tests, tests=2)
result = run_mini_receiver(
    model, environment, packet.to_receiver_text(), Path("outputs/mini/trajectory.json")
)
```

`GitHubVisibleFeedback` implements the public-worker callback for these frozen
development profiles. It checks the dispatched commit, original-source control
and candidate hash before returning only that condition's observations. Model
credentials never go to GitHub. Dollar prices for a compatible alias may be
unknown; reported tokens are recorded independently and are not an invoice.

## Interpretation

Original tests can detect syntax errors and regressions but may not cover the
reported issue. Passing them is **not** official task acceptance. Official grading
runs only after generation and never enters model context. This first diagnostic
reuses the same already-used sender states and prepared contexts for all three
conditions, with fresh candidate generation. The controller, prompt and step
semantics differ from the older run, so the two runs cannot be pooled or used to
attribute all changes solely to test feedback. Formal 200 tasks remain unused.

The [primary official results](../evals/public_swe/results/2026-10-12-mini-takeover-v1-grading/README.md)
are 0/2 in every condition. The
[separate correction](../evals/public_swe/results/2026-10-12-mini-takeover-v2-grading/README.md)
retains a provider failure and does not replace the initial interface failures.
The next step is one public-issue reproduction spanning the handoff: researcher
records its real failure; the packet preserves the script artifact, command and
expected behavior; the coder reruns it after editing, alongside original tests.
