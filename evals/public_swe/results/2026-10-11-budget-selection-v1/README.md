# Budget-aware original-state selection

Eleven already-used development sender states, eleven selector requests, eleven
valid packets within the unchanged 4,000-token contracts. This is a mechanism
validation, not eleven new tasks or a downstream success comparison.

The new selector sees the canonical packet's fixed cost, the remaining material
budget and conservative insertion estimates. No goal is shortened, essential
state is not silently dropped, and compilation still checks the complete packet.
All 34 retained packet spans were independently checked against exact
original sender content; sender and contract bytes remain unchanged.

| Task | Packet estimate | Fixed packet cost | Available source budget |
|---|---:|---:|---:|
| sympy__sympy-18698 | 1,631 | 172 | 3,828 |
| scikit-learn__scikit-learn-25931 | 2,410 | 810 | 3,190 |
| pylint-dev__pylint-6528 | 1,921 | 684 | 3,316 |
| mwaskom__seaborn-3069 | 2,579 | 357 | 3,643 |
| psf__requests-2931 | 954 | 125 | 3,875 |
| matplotlib__matplotlib-20859 | 1,721 | 732 | 3,268 |
| django__django-14608 | 652 | 208 | 3,792 |
| pytest-dev__pytest-10081 | 1,175 | 826 | 3,174 |
| sphinx-doc__sphinx-7590 | 502 | 213 | 3,787 |
| astropy__astropy-13398 | 3,183 | 1,428 | 2,572 |
| pydata__xarray-6721 | 3,830 | 2,492 | 1,508 |

The long xarray goal previously produced a 4,266-token essential packet that was
rejected. This independent selection produces 3,830 tokens within the same
4,000-token budget. A separate receiver run measures whether it can solve the
task; validity here is not task success. Pytest uses the same limited observations
as before: the model returned a different valid plan, not additional evidence.

All eleven responses completed and reported usage: 138,244
total tokens. On the same original ten states, provider input changes from
98,066 to 115,350 (+17.62%).
Budget hints cost input tokens; the earlier 33.97% reduction measured a different
change and is not the effect of these hints. Usage is not a bill, and the gateway's
requested model alias does not verify its underlying identity.

`local-preparation-benchmark.json` records a local timing observation: 280 units
4.645 to 6.309 ms; a synthetic 2,240-unit input 36.686 to 49.048 ms. It includes
catalog creation, copies, planning estimates, serialization and schema; excludes
API, final compilation and receiver execution. The baseline reconstructs the old
request flow in current code. Hardware was not recorded and timings were not
interleaved; this does not establish p95 or general linear dependency-graph time.
The script and the xarray input are committed for inspection and local replay.

`reproduce.py.txt`, raw requests/responses, input hashes, the implementation
revision and run status are retained. No automatic retries or held-out tasks.
