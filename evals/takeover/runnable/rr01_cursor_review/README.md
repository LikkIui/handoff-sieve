# RR-01 runnable fixture

This directory turns the RR-01 comprehension pilot into an executable review
task. It has not been run by a provider and contains no provider result.

Only `starter/` is shown to the receiving reviewer. It contains the active
candidate implementation and no expected verdict. `acceptance.py` remains on
the host side: it executes the candidate probes, derives the registered blocker
set from behavior, and checks the reviewer's structured verdict against that
derived result.

The fixture does not trust a model's self-assessment and does not store a
hand-written verdict oracle in the receiver workspace.
