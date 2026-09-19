# Decision backend Pareto analysis

Contract: `decision-capability-v1`

No universal winner declared. Dominance is per-capability only.

## rlm.worker_needed

**Pareto-optimal:** decider_2b, laya_421m
**Excluded (dangerous false > 0):** openjev_06b, nanojev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.667 | 71.57917199947406 | 0.4919 | 0.000 | 3 |
| laya_421m | 0.333 | 276.40691999840783 | 0.6354 | 0.000 | 3 |
| nanojev_06b | 0.333 | 33.388554002158344 | 0.8947 | 0.333 | 3 |
| openjev_06b | 0.667 | 27.587042000959627 | 0.6786 | 0.333 | 3 |

## tool_family_select

**Pareto-optimal:** openjev_06b, decider_2b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 1.000 | 63.185101502313046 | 0.0380 | 0.000 | 2 |
| laya_421m | 1.000 | 289.8385479966237 | 0.2538 | 0.000 | 2 |
| nanojev_06b | 0.000 | 33.86345899707521 | 0.9791 | 0.000 | 2 |
| openjev_06b | 0.000 | 29.166210002586013 | 1.5919 | 0.000 | 2 |

**Dominated by:**
- `nanojev_06b` ← `openjev_06b`

## retry_or_escalate

**Pareto-optimal:** (none with runnable results)
**Excluded (dangerous false > 0):** openjev_06b, decider_2b, nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 52.470861501205945 | 0.5604 | 0.500 | 2 |
| laya_421m | 0.500 | 248.89807249928708 | 0.8889 | 0.500 | 2 |
| nanojev_06b | 0.500 | 33.16040150093613 | 0.5467 | 0.500 | 2 |
| openjev_06b | 0.500 | 28.106557994760806 | 0.9999 | 0.500 | 2 |

## context_compress_needed

**Pareto-optimal:** openjev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 50.428229002136504 | 0.6150 | 0.000 | 2 |
| laya_421m | 0.000 | 208.4549169994716 | 0.7104 | 0.000 | 2 |
| nanojev_06b | 0.500 | 32.83104750153143 | 0.7717 | 0.000 | 2 |
| openjev_06b | 0.500 | 26.81066800141707 | 1.0000 | 0.000 | 2 |

**Dominated by:**
- `decider_2b` ← `openjev_06b`, `nanojev_06b`
- `nanojev_06b` ← `openjev_06b`

## verification_needed

**Pareto-optimal:** openjev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 52.60820599869476 | 0.4736 | 0.000 | 2 |
| laya_421m | 1.000 | 213.56547950199456 | 0.3654 | 0.000 | 2 |
| nanojev_06b | 0.500 | 34.420842999679735 | 0.6039 | 0.000 | 2 |
| openjev_06b | 0.500 | 33.95300200281781 | 0.9807 | 0.000 | 2 |

**Dominated by:**
- `decider_2b` ← `openjev_06b`, `nanojev_06b`
- `nanojev_06b` ← `openjev_06b`

