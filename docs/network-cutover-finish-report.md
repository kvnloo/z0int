# Network cutover finish report (MASTER §8)

Date: 2026-09-18
Canonical runtime repo: **kvnloo/z0intelligence** (package/CLI `z0int`, dist `openjev-phase1`)

## Phase status

| Phase | Repo | Branch | Base | Final SHA | PR | Tests |
|-------|------|--------|------|-----------|----|-------|
| A (done prior) | z0intelligence | master | master | `5e7cf4a` | #9 merged | 164+ |
| B AODL | aodl | feat/aodl-contract-importable | nightly | `1fa80da` | [#16](https://github.com/kvnloo/aodl/pull/16) | corpus OK + unittest API |
| C EL | evolution-lab | feat/z0int-cutover-export | nightly | `2c95b59` | [#17](https://github.com/kvnloo/evolution-lab/pull/17) | test_export_z0int 2 passed |
| D Kerdoios | kerdoios | feat/z0int-cutover-observations | main | `3e61c2f` | [#49](https://github.com/kvnloo/kerdoios/pull/49) | 27 unittest OK |
| E–F harness | z0intelligence | feat/network-cutover-harness-adapters | master | tip after fixup | [#10](https://github.com/kvnloo/z0intelligence/pull/10) | hermes+phaseA + full 168 on prior tip |

## Ownership moved

- **Production preflight**: z0intelligence only (EL preflight = research/shadow).
- **Candidate artifacts**: EL `export-z0int` emits always-`candidate`; z0int import never promotes.
- **AODL validation**: importable `aodl_contract` (hotl-0.2 + `spec_revision()`); CLI=same impl.
- **Observations**: Kerdoios V2 `execution_completed` ≠ `verified_success` (null ≠ success); `observations import`.
- **Allocation**: Kerdoios accepts `z0int.allocation_request.v1`; multi-quota shared groups; ExecutionPlan v2 metadata only.
- **Harness**: OMP bridge via `omp-extensions/` + `z0int onboard` symlink only; Hermes thin adapter `adapters/hermes_z0int/`.

## Remaining duplicates / follow-ups

- Historical mentions of `kvnloo/openjev` / `kvnloo/z0int` remain in RESEARCH.md / FUTURE_SLICE provenance (intentional).
- EL optional dep still named `openjev-phase1` (package name frozen) pointing at z0intelligence git URL.
- PRs not yet squash-merged (await CI / review).
- Live OMP one-restart after V2 shim still optional; **execution stays log_only**.
- `src/z0int/train.py` may optionally import evolution_lab for offline distill — not production bridge path.

## Dependency-cycle audit (production runtime)

| Edge | Status |
|------|--------|
| z0intelligence → EL | offline/train optional only; bridge preflight has no EL |
| z0intelligence → Kerdoios | export projection only (`kerdoios_export`); no import of kerdoios package |
| z0intelligence → AODL | examples only; no import |
| AODL → z0int/EL/Kerdoios | **none** |
| EL → z0int | optional dep URL only; export is file format; no registry write |
| Kerdoios → z0int | **none** (accepts JSON schemas only) |

**No production cycle** `z0intelligence ↔ EL/Kerdoios/AODL`.

## Blocked / not done

- Merge of open PRs to protected branches (human/CI).
- Multi-session live concurrency smoke (3 OMP + 1 Hermes) not executed this pass.
- Do **not** flip bridge `execution: log_only`.
