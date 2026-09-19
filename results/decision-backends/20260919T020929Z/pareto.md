# Decision backend Pareto analysis

Contract: `decision-capability-v1`

No universal winner declared. Dominance is per-capability only.

## rlm.worker_needed

**Pareto-optimal:** decider_2b, laya_421m
**Excluded (dangerous false > 0):** nanojev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.667 | 49.97558699687943 | 0.4919 | 0.000 | 3 |
| laya_421m | 0.333 | 299.1124469990609 | 0.6354 | 0.000 | 3 |
| nanojev_06b | 0.333 | 34.69891200074926 | 0.8947 | 0.333 | 3 |

## tool_family_select

**Pareto-optimal:** decider_2b, nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 1.000 | 48.36008599886554 | 0.0380 | 0.000 | 2 |
| laya_421m | 1.000 | 289.16772700176807 | 0.2538 | 0.000 | 2 |
| nanojev_06b | 0.000 | 33.90908399887849 | 0.9791 | 0.000 | 2 |

## retry_or_escalate

**Pareto-optimal:** (none with runnable results)
**Excluded (dangerous false > 0):** decider_2b, nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 47.7667159975681 | 0.5604 | 0.500 | 2 |
| laya_421m | 0.500 | 263.80365699878894 | 0.8889 | 0.500 | 2 |
| nanojev_06b | 0.500 | 33.622655497310916 | 0.5467 | 0.500 | 2 |

## context_compress_needed

**Pareto-optimal:** nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 47.085972502827644 | 0.6150 | 0.000 | 2 |
| laya_421m | 0.000 | 219.58994699889445 | 0.7104 | 0.000 | 2 |
| nanojev_06b | 0.500 | 34.135365996917244 | 0.7717 | 0.000 | 2 |

**Dominated by:**
- `decider_2b` ← `nanojev_06b`

## verification_needed

**Pareto-optimal:** nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 46.2235734994465 | 0.4736 | 0.000 | 2 |
| laya_421m | 1.000 | 220.0664849988243 | 0.3654 | 0.000 | 2 |
| nanojev_06b | 0.500 | 33.625393498368794 | 0.6039 | 0.000 | 2 |

**Dominated by:**
- `decider_2b` ← `nanojev_06b`

