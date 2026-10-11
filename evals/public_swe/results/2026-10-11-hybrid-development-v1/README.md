# Stopped literal-copy prototype

This first hybrid prototype asked the model to return verbatim string excerpts.
It was stopped after repeated local rejections: quotes changed escaping,
newlines or original line labels. No fuzzy matching, silent repair or receiver
fallback was applied. No receiver episode started.

`run-status.json` records **11 requests, 8 completed, 1 valid packet and 7 rejected
packets**. Three in-flight requests were interrupted and lack reported usage;
their cost is unknown. Known completed usage totals **68,696 provider tokens**.
The original plan was sixteen preparation calls; unstarted tasks are not counted
as executed calls or successes. No success-rate claim is made.

Raw calls, individual selection reports, the planned manifest, reproducer and
the two evaluated source snapshots are retained. The corrected line-coordinate
run has a separate directory and must not overwrite or pool this diagnostic.
