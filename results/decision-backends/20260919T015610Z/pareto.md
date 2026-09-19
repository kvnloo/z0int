# Decision backend Pareto analysis

Contract: `decision-capability-v1`

No universal winner declared. Dominance is per-capability only.

## rlm.worker_needed

**Pareto-optimal:** laya_421m
**Excluded (dangerous false > 0):** nanojev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| laya_421m | 0.333 | 349.35645799851045 | 0.6354 | 0.000 | 3 |
| nanojev_06b | 0.333 | 38.98114900221117 | 0.8947 | 0.333 | 3 |

## tool_family_select

**Pareto-optimal:** nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| laya_421m | 1.000 | 325.79083849850576 | 0.2538 | 0.000 | 2 |
| nanojev_06b | 0.000 | 40.954514999612 | 0.9791 | 0.000 | 2 |

## retry_or_escalate

**Pareto-optimal:** (none with runnable results)
**Excluded (dangerous false > 0):** nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| laya_421m | 0.500 | 277.65810750133824 | 0.8889 | 0.500 | 2 |
| nanojev_06b | 0.500 | 60.221114501473494 | 0.5467 | 0.500 | 2 |

## context_compress_needed

**Pareto-optimal:** nanojev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| laya_421m | 0.000 | 274.06330699886894 | 0.7104 | 0.000 | 2 |
| nanojev_06b | 0.500 | 48.302654999133665 | 0.7717 | 0.000 | 2 |

**Dominated by:**
- `laya_421m` ← `nanojev_06b`

## verification_needed

**Pareto-optimal:** nanojev_06b, laya_421m

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| laya_421m | 1.000 | 301.0185549974267 | 0.3654 | 0.000 | 2 |
| nanojev_06b | 0.500 | 37.87847800049349 | 0.6039 | 0.000 | 2 |

