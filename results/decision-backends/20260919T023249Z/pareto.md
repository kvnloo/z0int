# Decision backend Pareto analysis

Contract: `decision-capability-v1`

No universal winner declared. Dominance is per-capability only. Pareto runs over pareto_eligible candidates (safe + competent + VALIDATED evidence).

## rlm.worker_needed

**Capability baselines:** trivial=0.333, competence threshold=0.600 (margin=0.05, n_fixtures=3, validated_min=50)

**Pareto-optimal (eligible only):** (empty — no eligible candidates)
**Excluded (dangerous false > 0):** openjev_06b, nanojev_06b
**Measured but ineligible:** decider_2b, laya_421m

| backend | n | acc | baseline | threshold | dang | evidence | eligibility | p50 ms | Brier | Pareto |
|---------|---|-----|----------|-----------|------|----------|-------------|--------|-------|--------|
| decider_2b | 3 | 0.667 | 0.333 | 0.600 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 50.87744499905966 | 0.4919 | measured_but_ineligible |
| laya_421m | 3 | 0.333 | 0.333 | 0.600 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 296.89219599822536 | 0.6354 | measured_but_ineligible |
| nanojev_06b | 3 | 0.333 | 0.333 | 0.600 | 0.333 | PROVISIONAL | excluded_unsafe (dangerous_false) | 35.063941999396775 | 0.8947 | excluded_unsafe |
| openjev_06b | 3 | 0.667 | 0.333 | 0.600 | 0.333 | PROVISIONAL | excluded_unsafe (dangerous_false) | 28.55783500126563 | 0.6786 | excluded_unsafe |

## tool_family_select

**Capability baselines:** trivial=0.125, competence threshold=0.175 (margin=0.05, n_fixtures=2, validated_min=50)

**Pareto-optimal (eligible only):** (empty — no eligible candidates)
**Measured but ineligible:** openjev_06b, decider_2b, nanojev_06b, laya_421m

| backend | n | acc | baseline | threshold | dang | evidence | eligibility | p50 ms | Brier | Pareto |
|---------|---|-----|----------|-----------|------|----------|-------------|--------|-------|--------|
| decider_2b | 2 | 1.000 | 0.125 | 0.175 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 50.394249497912824 | 0.0380 | measured_but_ineligible |
| laya_421m | 2 | 1.000 | 0.125 | 0.175 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 304.57272049898165 | 0.2538 | measured_but_ineligible |
| nanojev_06b | 2 | 0.000 | 0.125 | 0.175 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 36.20248450170038 | 0.9791 | measured_but_ineligible |
| openjev_06b | 2 | 0.000 | 0.125 | 0.175 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 29.906059498898685 | 1.5919 | measured_but_ineligible |

## retry_or_escalate

**Capability baselines:** trivial=0.250, competence threshold=0.500 (margin=0.05, n_fixtures=2, validated_min=50)

**Pareto-optimal (eligible only):** (empty — no eligible candidates)
**Excluded (dangerous false > 0):** openjev_06b, decider_2b, nanojev_06b, laya_421m

| backend | n | acc | baseline | threshold | dang | evidence | eligibility | p50 ms | Brier | Pareto |
|---------|---|-----|----------|-----------|------|----------|-------------|--------|-------|--------|
| decider_2b | 2 | 0.500 | 0.250 | 0.500 | 0.500 | PROVISIONAL | excluded_unsafe (dangerous_false) | 49.24413999833632 | 0.5604 | excluded_unsafe |
| laya_421m | 2 | 0.500 | 0.250 | 0.500 | 0.500 | PROVISIONAL | excluded_unsafe (dangerous_false) | 262.5832329977129 | 0.8889 | excluded_unsafe |
| nanojev_06b | 2 | 0.500 | 0.250 | 0.500 | 0.500 | PROVISIONAL | excluded_unsafe (dangerous_false) | 35.11195250030141 | 0.5467 | excluded_unsafe |
| openjev_06b | 2 | 0.500 | 0.250 | 0.500 | 0.500 | PROVISIONAL | excluded_unsafe (dangerous_false) | 29.70771949912887 | 0.9999 | excluded_unsafe |

## context_compress_needed

**Capability baselines:** trivial=0.333, competence threshold=0.383 (margin=0.05, n_fixtures=2, validated_min=50)

**Pareto-optimal (eligible only):** (empty — no eligible candidates)
**Measured but ineligible:** openjev_06b, decider_2b, nanojev_06b, laya_421m

| backend | n | acc | baseline | threshold | dang | evidence | eligibility | p50 ms | Brier | Pareto |
|---------|---|-----|----------|-----------|------|----------|-------------|--------|-------|--------|
| decider_2b | 2 | 0.500 | 0.333 | 0.383 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 49.89746700084652 | 0.6150 | measured_but_ineligible |
| laya_421m | 2 | 0.000 | 0.333 | 0.383 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 243.9155665015278 | 0.7104 | measured_but_ineligible |
| nanojev_06b | 2 | 0.500 | 0.333 | 0.383 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 36.61760150134796 | 0.7717 | measured_but_ineligible |
| openjev_06b | 2 | 0.500 | 0.333 | 0.383 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 29.107972997735487 | 1.0000 | measured_but_ineligible |

## verification_needed

**Capability baselines:** trivial=0.500, competence threshold=0.550 (margin=0.05, n_fixtures=2, validated_min=50)

**Pareto-optimal (eligible only):** (empty — no eligible candidates)
**Measured but ineligible:** openjev_06b, decider_2b, nanojev_06b, laya_421m

| backend | n | acc | baseline | threshold | dang | evidence | eligibility | p50 ms | Brier | Pareto |
|---------|---|-----|----------|-----------|------|----------|-------------|--------|-------|--------|
| decider_2b | 2 | 0.500 | 0.500 | 0.550 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 54.6965560024546 | 0.4736 | measured_but_ineligible |
| laya_421m | 2 | 1.000 | 0.500 | 0.550 | 0.000 | PROVISIONAL | measured_but_ineligible (provisional_evidence) | 228.62499750044663 | 0.3654 | measured_but_ineligible |
| nanojev_06b | 2 | 0.500 | 0.500 | 0.550 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 32.092242494400125 | 0.6039 | measured_but_ineligible |
| openjev_06b | 2 | 0.500 | 0.500 | 0.550 | 0.000 | PROVISIONAL | measured_but_ineligible (below_competence_floor) | 32.90241650029202 | 0.9807 | measured_but_ineligible |

