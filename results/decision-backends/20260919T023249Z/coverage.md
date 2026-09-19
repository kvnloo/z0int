SYSTEM TOKENOMICS COVERAGE · 7d

Traces
────────────────────────────────────────
Traces                       44
Events                       132

Physical usage
────────────────────────────────────────
Incremental provider-metered 33
Zero local (metered)         0
Aggregate-only               0
Unmetered                    11
Physical coverage            75.0%

Counterfactuals
────────────────────────────────────────
Paired measured              0
Estimated                    0
Missing                      44
Counterfactual coverage      0.0%

Outcomes
────────────────────────────────────────
Verified/gold                22
Negative                     22
Execution-only               0
Unknown                      0
Verified coverage            50.0%

Measurement levels
────────────────────────────────────────
M3                           0
M2                           33
M1                           0
M0                           11

By mechanism
────────────────────────────────────────
routing          traces   44  metered   33  baseline_cov 0.0%
other            traces   24  metered   18  baseline_cov 0.0%
rlm              traces   12  metered    9  baseline_cov 0.0%
context          traces    8  metered    6  baseline_cov 0.0%
omp              traces    8  metered    6  baseline_cov 0.0%

FRONTIER COMPUTE (trace rollup — not mechanism sum)
────────────────────────────────────────
Actual frontier tokens       3874
Measured avoided             0
Estimated avoided            0
Unknown baseline traces      44

FLOW (separate lane)
────────────────────────────────────────
Prepare events               0
Net prepare value            0.0 ms
Speculation overhead         0.0 ms

Highest-value measurement gaps
────────────────────────────────────────
rlm          rlm.worker_needed      n=12   baseline_cov=0%  EIV=high
routing      rlm.worker_needed      n=12   baseline_cov=0%  EIV=high
other        tool_family_select     n=8    baseline_cov=0%  EIV=high
routing      tool_family_select     n=8    baseline_cov=0%  EIV=high
other        retry_or_escalate      n=8    baseline_cov=0%  EIV=high
routing      retry_or_escalate      n=8    baseline_cov=0%  EIV=high
other        verification_needed    n=8    baseline_cov=0%  EIV=high
routing      verification_needed    n=8    baseline_cov=0%  EIV=high

Period 2026-09-12T02:33:34.472769+00:00 → 2026-09-19T02:33:34.472769+00:00
Coverage does not alter savings totals.

