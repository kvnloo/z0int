"""z0int root CLI.

Deterministic lifecycle. Agents should invoke these commands instead of
reproducing setup steps from README memory.

Future compiler stack (library modules still usable via python -m):
  z0int routine|cascade|aodl|repair|abab …
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _print(data: Any, *, as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    elif human is not None:
        print(human)
    else:
        print(json.dumps(data, indent=2, default=str))


def _bool_opt(s: str) -> bool:
    return s.lower() in ("1", "true", "yes", "y")


def cmd_doctor(*, as_json: bool) -> int:
    from .doctor import format_human, run_doctor

    rep = run_doctor()
    _print(rep.to_dict(), as_json=as_json, human=format_human(rep))
    return 0 if rep.ok else 1


def cmd_status(*, as_json: bool) -> int:
    from .status import format_human, run_status

    st = run_status()
    _print(st, as_json=as_json, human=format_human(st))
    return 0 if st.get("ok", True) else 1


def cmd_onboard(
    *,
    auto: bool,
    force: bool,
    dry_run: bool,
    sync_models: bool,
    skip_evolution_lab: bool,
    as_json: bool,
) -> int:
    from .onboard import run_onboard

    report = run_onboard(
        auto=auto,
        force=force,
        dry_run=dry_run,
        sync_models=sync_models,
        skip_evolution_lab=skip_evolution_lab,
    )
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("z0int onboard")
        print(f"  ok={report.get('ok')}  state={report.get('state_path')}")
        for name, res in (report.get("results") or {}).items():
            mark = "✓" if res.get("ok") and not res.get("error") else ("○" if res.get("skipped") else "✗")
            extra = " skipped" if res.get("skipped") else ""
            err = res.get("error")
            print(f"  {mark} {name}{extra}" + (f"  {err}" if err else ""))
        nxt = report.get("next") or []
        if nxt:
            print("\nNext:")
            for a in nxt:
                print(f"  - {a}")
    return 0 if report.get("ok") else 1


def cmd_models_plan(*, as_json: bool) -> int:
    from .models_mgmt import plan_models

    plan = plan_models()
    if as_json:
        print(json.dumps(plan, indent=2, default=str))
    else:
        print("z0int models plan")
        print(f"  gpu: {plan.get('gpu_name')}  vram_gb={plan.get('vram_gb')}")
        print(f"  {plan.get('recommendation')}")
        print(f"  resident: {plan.get('resident')}")
        print(f"  on_demand: {plan.get('on_demand')}")
    return 0


def cmd_models_sync(*, which: str, dry_run: bool, as_json: bool) -> int:
    from .models_mgmt import sync_models

    result = sync_models(which=which, dry_run=dry_run)
    _print(result, as_json=as_json)
    bad = [r for r in result.get("results") or [] if r.get("status") == "error"]
    return 1 if bad else 0


def cmd_data_discover(*, as_json: bool) -> int:
    from . import paths
    from .doctor import discover_data_sources

    data = discover_data_sources()
    out = {
        "schema": "z0int.sources_discovered.v1",
        "sources": data,
        "home": str(paths.home()),
    }
    paths.ensure_layout()
    dest = paths.home() / "sources" / "discovered.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    out["path"] = str(dest)
    _print(out, as_json=as_json)
    return 0


def cmd_receipt_emit(*, args: argparse.Namespace) -> int:
    from .receipt import append_receipt, build_receipt

    r = build_receipt(
        trace_id=args.trace_id,
        session_id=args.session_id,
        capability_id=args.capability_id,
        provider=args.provider,
        model=args.model,
        prediction=args.prediction,
        confidence=args.confidence,
        action_taken=args.action,
        route=args.route,
        execution=args.execution,
        latency_ms=args.latency_ms,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        baseline_input_tokens=args.baseline_in,
        baseline_output_tokens=args.baseline_out,
        estimated_frontier_tokens_avoided=args.avoided,
    )
    row = append_receipt(r)
    print(json.dumps(row, indent=2, default=str))
    return 0


def cmd_receipt_join(*, args: argparse.Namespace) -> int:
    from .receipt import Outcome, join_outcome

    def flag(name: str) -> bool | None:
        v = getattr(args, name, None)
        return v if v is not None else None

    oc = Outcome(
        execution_completed=flag("execution_completed"),
        verified_success=flag("verified_success"),
        verified=flag("verified"),
        success=flag("success"),
        tool_ok=flag("tool_ok"),
        test_pass=flag("test_pass"),
        task_done=flag("task_done"),
        user_correction=flag("user_correction"),
        reverted=flag("reverted"),
        verifier_ok=flag("verifier_ok"),
        ci_failed=flag("ci_failed"),
        pr_merged=flag("pr_merged"),
        note=args.note,
        source=args.source or "cli",
        verification_source=getattr(args, "verification_source", None),
    )
    joined = join_outcome(args.trace_id, oc)
    print(json.dumps(joined, indent=2, default=str))
    return 0 if joined else 1


def cmd_receipt_close(*, args: argparse.Namespace) -> int:
    from .receipt import Outcome, close_turn

    def flag(name: str) -> bool | None:
        v = getattr(args, name, None)
        return v if v is not None else None

    oc = None
    if any(
        flag(n) is not None
        for n in (
            "execution_completed",
            "verified_success",
            "verified",
            "success",
            "tool_ok",
            "test_pass",
            "task_done",
            "user_correction",
            "reverted",
            "verifier_ok",
            "ci_failed",
            "pr_merged",
        )
    ) or args.note:
        oc = Outcome(
            execution_completed=flag("execution_completed"),
            verified_success=flag("verified_success"),
            verified=flag("verified"),
            success=flag("success"),
            tool_ok=flag("tool_ok"),
            test_pass=flag("test_pass"),
            task_done=flag("task_done"),
            user_correction=flag("user_correction"),
            reverted=flag("reverted"),
            verifier_ok=flag("verifier_ok"),
            ci_failed=flag("ci_failed"),
            pr_merged=flag("pr_merged"),
            note=args.note,
            source=args.source or "cli",
            verification_source=getattr(args, "verification_source", None),
        )
    closed = close_turn(
        args.trace_id,
        measured_frontier_tokens=args.measured,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        cached_input_tokens=args.cached_input_tokens,
        latency_ms=args.latency_ms,
        provider=args.provider,
        model=args.model,
        outcome=oc,
        source=args.source or "cli",
    )
    print(json.dumps(closed, indent=2, default=str))
    return 0

def cmd_receipt_summary(*, as_json: bool) -> int:
    from .receipt import summarize_tokenomics

    s = summarize_tokenomics()
    _print(
        s,
        as_json=as_json,
        human=(
            "z0int receipts\n"
            f"  rows={s.get('rows')}  avoided_est={s.get('frontier_tokens_avoided_est')}\n"
            f"  with_outcome={s.get('rows_with_outcome')}  caps={s.get('by_capability')}"
        ),
    )
    return 0

def cmd_receipt_scrub(*, as_json: bool, dry_run: bool) -> int:
    from .receipt import scrub_contaminated_outcomes

    s = scrub_contaminated_outcomes(dry_run=dry_run)
    _print(
        s,
        as_json=as_json,
        human=(
            "z0int outcome scrub\n"
            f"  scanned={s.get('scanned_joins')} unique={s.get('unique_traces')}\n"
            f"  contaminated={s.get('contaminated_latest')} "
            f"rewritten={s.get('rewritten')} dry_run={s.get('dry_run')}"
        ),
    )
    return 0




def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="z0int",
        description=(
            "Personal intelligence lifecycle — onboard, doctor, status, models, "
            "receipt, routine/cascade/aodl/repair/abab"
        ),
    )
    p.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _json_flag(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable JSON output")

    d = sub.add_parser("doctor", help="Inspect hardware, deps, harnesses, data sources")
    _json_flag(d)
    s = sub.add_parser("status", help="Product status dashboard")
    _json_flag(s)

    on = sub.add_parser("onboard", help="Idempotent setup pipeline (safe defaults)")
    _json_flag(on)
    on.add_argument("--auto", action="store_true", default=True, help="Non-interactive safe path (default)")
    on.add_argument("--force", action="store_true", help="Re-run steps marked done")
    on.add_argument("--dry-run", action="store_true", help="Plan only; no clone/pip/symlink/download")
    on.add_argument("--sync-models", action="store_true", help="Download resident HF weights")
    on.add_argument("--skip-evolution-lab", action="store_true")

    ms = sub.add_parser("models", help="Model plan / sync")
    ms_sub = ms.add_subparsers(dest="models_cmd", required=True)
    mp = ms_sub.add_parser("plan", help="Hardware-aware resident / on-demand plan")
    _json_flag(mp)
    mss = ms_sub.add_parser("sync", help="Download planned HF models")
    _json_flag(mss)
    mss.add_argument("--which", choices=("resident", "on_demand", "all"), default="resident")
    mss.add_argument("--dry-run", action="store_true")

    data = sub.add_parser("data", help="Data source helpers")
    data_sub = data.add_subparsers(dest="data_cmd", required=True)
    dd = data_sub.add_parser("discover", help="Find Hermes/OMP/Codex/export paths")
    _json_flag(dd)

    rc = sub.add_parser("receipt", help="Decision receipt spine (trace → outcome → tokens)")
    rc_sub = rc.add_subparsers(dest="receipt_cmd", required=True)
    re = rc_sub.add_parser("emit", help="Append a decision receipt")
    _json_flag(re)
    re.add_argument("--trace-id", dest="trace_id", default=None)
    re.add_argument("--session-id", dest="session_id", default=None)
    re.add_argument("--capability-id", dest="capability_id", default=None)
    re.add_argument("--provider", default=None)
    re.add_argument("--model", default=None)
    re.add_argument("--prediction", default=None)
    re.add_argument("--confidence", type=float, default=None)
    re.add_argument("--action", default=None)
    re.add_argument("--route", default=None)
    re.add_argument("--execution", default="log_only")
    re.add_argument("--latency-ms", dest="latency_ms", type=float, default=None)
    re.add_argument("--input-tokens", dest="input_tokens", type=int, default=None)
    re.add_argument("--output-tokens", dest="output_tokens", type=int, default=None)
    re.add_argument("--baseline-in", dest="baseline_in", type=int, default=None)
    re.add_argument("--baseline-out", dest="baseline_out", type=int, default=None)
    re.add_argument("--avoided", type=int, default=None)

    rj = rc_sub.add_parser("join", help="Join world outcome to trace_id")
    _json_flag(rj)
    rj.add_argument("trace_id")
    for name, dest in (
        ("--execution-completed", "execution_completed"),
        ("--verified-success", "verified_success"),
        ("--success", "success"),
        ("--verified", "verified"),
        ("--tool-ok", "tool_ok"),
        ("--test-pass", "test_pass"),
        ("--task-done", "task_done"),
        ("--user-correction", "user_correction"),
        ("--reverted", "reverted"),
        ("--verifier-ok", "verifier_ok"),
        ("--ci-failed", "ci_failed"),
        ("--pr-merged", "pr_merged"),
    ):
        rj.add_argument(name, dest=dest, type=_bool_opt, default=None)
    rj.add_argument("--note", default=None)
    rj.add_argument("--source", default="cli")
    rj.add_argument("--verification-source", dest="verification_source", default=None)

    rcl = rc_sub.add_parser("close", help="Post-turn: measured tokens + optional outcome join")
    _json_flag(rcl)
    rcl.add_argument("trace_id")
    rcl.add_argument("--measured", type=int, default=None, help="measured frontier tokens total")
    rcl.add_argument("--input-tokens", dest="input_tokens", type=int, default=None)
    rcl.add_argument("--output-tokens", dest="output_tokens", type=int, default=None)
    rcl.add_argument("--cached-input-tokens", dest="cached_input_tokens", type=int, default=None)
    rcl.add_argument("--latency-ms", dest="latency_ms", type=float, default=None)
    rcl.add_argument("--provider", default=None)
    rcl.add_argument("--model", default=None)
    for name, dest in (
        ("--execution-completed", "execution_completed"),
        ("--verified-success", "verified_success"),
        ("--success", "success"),
        ("--verified", "verified"),
        ("--tool-ok", "tool_ok"),
        ("--test-pass", "test_pass"),
        ("--task-done", "task_done"),
        ("--user-correction", "user_correction"),
        ("--reverted", "reverted"),
        ("--verifier-ok", "verifier_ok"),
        ("--ci-failed", "ci_failed"),
        ("--pr-merged", "pr_merged"),
    ):
        rcl.add_argument(name, dest=dest, type=_bool_opt, default=None)
    rcl.add_argument("--note", default=None)
    rcl.add_argument("--source", default="cli")
    rcl.add_argument("--verification-source", dest="verification_source", default=None)

    rs = rc_sub.add_parser("summary", help="Tokenomics rollup from receipts + bridge")
    _json_flag(rs)

    rscrub = rc_sub.add_parser(
        "scrub",
        help="Append corrections for false-gold outcomes (no verification signal)",
    )
    _json_flag(rscrub)
    rscrub.add_argument(
        "--dry-run",
        action="store_true",
        help="Report contaminated rows without rewriting",
    )


    cf = sub.add_parser(
        "counterfactual",
        help="Paired Grok reference cartography (historical mine + non-inferiority)",
    )
    cf_sub = cf.add_subparsers(dest="counterfactual_cmd", required=True)
    cfm = cf_sub.add_parser("mine", help="Mine historical Grok OMP turns into replay snapshots")
    _json_flag(cfm)
    cfm.add_argument(
        "--sessions-root",
        default=None,
        help="OMP sessions root (default: ~/.omp/agent/sessions or symlink target)",
    )
    cfm.add_argument("--limit", type=int, default=5000, help="Max assistant turns to scan")
    cfm.add_argument("--provider-substr", default="xai,grok", help="Comma substrings for reference providers/models")
    cfs = cf_sub.add_parser("summary", help="Replay grade / pair inventory")
    _json_flag(cfs)
    cfi = cf_sub.add_parser(
        "worker-needed-ingest",
        help="Ingest OMP rlm.worker_needed paired-replay results into Tokenomics analytics",
    )
    _json_flag(cfi)
    cfi.add_argument("--limit", type=int, default=50, help="Max recent result rows to ingest")

    # Future compiler stack — remainder args forwarded to module CLIs.


    cx = sub.add_parser("context", help="Provenance-preserving context resolution")
    cx_sub = cx.add_subparsers(dest="context_cmd", required=True)
    cxr = cx_sub.add_parser("resolve", help="resolve_context — source-backed evidence packet")
    cxr.add_argument("--json", action="store_true")
    cxr.add_argument("--query", default=None, help="Natural-language information need")
    cxr.add_argument("--path", action="append", default=[], help="Exact file path need (repeatable)")
    cxr.add_argument("--task-id", default=None)
    cxr.add_argument("--project-root", default=None)
    cxr.add_argument("--no-qmd", action="store_true")
    cxr.add_argument("--allow-memory", action="store_true")
    cxr.add_argument("--input", default=None, help="JSON file with needs[]")


    osc = sub.add_parser(
        "os-context",
        help="OS Episode Compiler: workspace-copilot → z0int vault (sanitized only)",
    )
    osc_sub = osc.add_subparsers(dest="os_context_cmd", required=True)
    osc_imp = osc_sub.add_parser("import", help="Compile closed episodes + shadow into ~/.z0int/episodes/os_context")
    osc_imp.add_argument("--limit", type=int, default=50000)
    osc_imp.add_argument("--db", default=None, help="override workspace-copilot db path")
    _json_flag(osc_imp)
    osc_st = osc_sub.add_parser("stats", help="Live/imported os.next_context metrics")
    _json_flag(osc_st)
    osc_op = osc_sub.add_parser("next-operator", help="os.next_operator shadow coverage report")
    _json_flag(osc_op)

    tk = sub.add_parser("task", help="Authorized verified-loop task family (worktree + checkpoint)")
    tk_sub = tk.add_subparsers(dest="task_cmd", required=True)
    tka = tk_sub.add_parser("authorize", help="Authorize coding.bounded_worktree_patch checkpoint")
    tka.add_argument("--repo", required=True)
    tka.add_argument("--path", required=True, help="relative file to patch")
    tka.add_argument("--find", required=True)
    tka.add_argument("--replace", required=True)
    tka.add_argument("--req", action="append", default=[], help="requirement path (repeatable)")
    tka.add_argument("--task-id", default=None)
    tka.add_argument("--json", action="store_true")
    tkr = tk_sub.add_parser("run", help="Advance authorized task until verified (or --until)")
    tkr.add_argument("--task-id", required=True)
    tkr.add_argument("--until", default="verified", choices=["resolved", "worktree_ready", "patched", "verified"])
    tkr.add_argument("--allow-qmd", action="store_true")
    tkr.add_argument("--json", action="store_true")
    tks = tk_sub.add_parser("status", help="Show task checkpoint")
    tks.add_argument("--task-id", default=None)
    tks.add_argument("--json", action="store_true")
    tkf = tk_sub.add_parser("fixture", help="Create reference fixture repo + authorize + run")
    tkf.add_argument("--dir", required=True, help="directory for fixture git repo")
    tkf.add_argument("--task-id", default=None)
    tkf.add_argument("--json", action="store_true")

    be = sub.add_parser("backends", help="DecisionBackend registry (list / doctor / eval)")
    be_sub = be.add_subparsers(dest="backends_cmd", required=True)
    bel = be_sub.add_parser("list", help="List registered backends (no model load)")
    bel.add_argument("--json", action="store_true")
    bed = be_sub.add_parser("doctor", help="Filesystem/config backend health (no load by default)")
    bed.add_argument("--json", action="store_true")
    bed.add_argument("--load", action="store_true", help="Explicitly load weights (GPU)")
    bed.add_argument("--backend", default=None, help="Single backend id/alias")
    bec = be_sub.add_parser("capabilities", help="Show capability metadata")
    bec.add_argument("name", nargs="?", default="nanojev")
    bec.add_argument("--json", action="store_true")
    bee = be_sub.add_parser("eval", help="Run a DecisionRequest JSON through a backend")
    bee.add_argument("--backend", default="nanojev")
    bee.add_argument("--input", required=True, help="Path to request JSON")
    bee.add_argument("--json", action="store_true", default=True)
    beb = be_sub.add_parser("bench", help="Pareto benchmark decision backends (decision-capability-v1)")
    beb.add_argument("--contract", default="decision-capability-v1")
    beb.add_argument("--backend", default=None, help="Single roster candidate id")
    beb.add_argument("--capability", default=None, help="Filter to one capability")
    beb.add_argument("--fixtures", default=None, help="Path to examples.jsonl")
    beb.add_argument("--output", default=None, help="Output directory (default: results/decision-backends/<ts>)")
    beb.add_argument("--seed", type=int, default=0, help="Benchmark seed for pair_id / counterfactual pairing")
    beb.add_argument("--bootstrap-draws", type=int, default=500, help="Fixture-resample draws for Pareto inclusion probability")
    beb.add_argument("--json", action="store_true")


    art = sub.add_parser("artifacts", help="Candidate artifact inspect/import/list")
    art_sub = art.add_subparsers(dest="artifacts_cmd", required=True)
    arti = art_sub.add_parser("inspect", help="Validate manifest without installing")
    arti.add_argument("manifest")
    _json_flag(arti)
    artim = art_sub.add_parser("import", help="Import candidate artifact (never promotes)")
    artim.add_argument("manifest")
    artim.add_argument("--force", action="store_true")
    _json_flag(artim)
    artl = art_sub.add_parser("list", help="List installed specialists")
    _json_flag(artl)

    ct = sub.add_parser(
        "contrastive",
        help="Contrastive evidence-sufficiency eval (Nimble-style unit; no Nimble weights)",
    )
    ct_sub = ct.add_subparsers(dest="contrastive_cmd", required=True)
    ct_ev = ct_sub.add_parser("eval", help="Run four-condition probe on a family or built-in fixture")
    ct_ev.add_argument("--family-json", default=None, help="ContrastFamily JSON path")
    ct_ev.add_argument("--recipe-json", default=None, help="optional evidence-filter recipe JSON")
    ct_ev.add_argument("--store", action="store_true", help="write evidence_dependency record")
    _json_flag(ct_ev)
    ct_fx = ct_sub.add_parser("fixture", help="Print built-in project_status contrast family")
    _json_flag(ct_fx)
    ct_race = ct_sub.add_parser("race", help="Ordinary vs contrastive gate on frozen families")
    ct_race.add_argument("--families-jsonl", default=None, help="JSONL of ContrastFamily rows")
    ct_race.add_argument("--recipe-json", default=None)
    _json_flag(ct_race)

    cps = sub.add_parser(
        "context-state",
        help="Frozen capability context.current_project_state",
    )
    cps_sub = cps.add_subparsers(dest="context_state_cmd", required=True)
    cps_fx = cps_sub.add_parser("fixture", help="Built-in contrast family for P0 capability")
    _json_flag(cps_fx)
    cps_cmp = cps_sub.add_parser("compile", help="Compile episode from workspace snapshot JSON")
    cps_cmp.add_argument("snapshot_json")
    cps_cmp.add_argument("--store", action="store_true", help="append contrast family JSONL")
    _json_flag(cps_cmp)

    ar = sub.add_parser("autoresearch", help="Verified Trajectory Superoptimizer")
    ar_sub = ar.add_subparsers(dest="autoresearch_cmd", required=True)
    for _ar_name, _ar_help in (
        ("status", "Queue + resource governor status"),
        ("pause", "Pause background jobs"),
        ("resume", "Resume background jobs"),
        ("run-once", "Claim and run one ABAB job if resources allow"),
        ("daemon", "Run background loop (bounded iterations unless --forever)"),
        ("report", "Recent replay results"),
        ("enqueue", "Manually enqueue a verified trace"),
        ("research-once", "P0: Tokenomics gap → ResearchDriver → fly bench → ABAB"),
    ):
        _sp = ar_sub.add_parser(_ar_name, help=_ar_help)
        _json_flag(_sp)
        if _ar_name == "daemon":
            _sp.add_argument("--max-iterations", type=int, default=10)
            _sp.add_argument("--forever", action="store_true")
            _sp.add_argument("--poll-seconds", type=float, default=5.0)
        if _ar_name == "enqueue":
            _sp.add_argument("--trace-id", required=True)
            _sp.add_argument("--kind", default="context_policy", choices=["context_policy", "contrastive_evidence"])
            _sp.add_argument("--verifier-id", required=True)
            _sp.add_argument("--verified-success", type=str, default="true")
        if _ar_name == "research-once":
            _sp.add_argument("--driver", default="agy", choices=["agy", "deterministic"])
            _sp.add_argument("--evolution-lab-root", default=None)
            _sp.add_argument("--force-resources", action="store_true")

    kerd = sub.add_parser("kerdoios", help="Kerdoios projection helpers (receipts stay authoritative)")
    kerd_sub = kerd.add_subparsers(dest="kerdoios_cmd", required=True)
    kerde = kerd_sub.add_parser("export-observations", help="Export allocation_observation.v1 rows")
    kerde.add_argument("--since", type=float, default=None)
    kerde.add_argument("--output", default=None)
    _json_flag(kerde)

    pf = sub.add_parser("preflight", help="z0intelligence production preflight (no Evolution Lab)")
    pf.add_argument("prompt")
    pf.add_argument("--capability-id", default=None)
    _json_flag(pf)

    for name, help_txt in (
        ("routine", "Compile/apply specialist region routines (→ z0int.routines)"),
        ("cascade", "Optimize specialist cascades for premium tokens (→ z0int.cascade)"),
        ("aodl", "Bind routines/cascades into AODL strategy docs (→ z0int.aodl)"),
        ("repair", "Counterexample-driven routine repair (→ z0int.refinement)"),
        ("abab", "ABAB experiment archive helpers (→ z0int.abab)"),
    ):
        sp = sub.add_parser(name, help=help_txt)
        sp.add_argument(
            "module_argv",
            nargs=argparse.REMAINDER,
            help=f"Arguments for the {name} subcommand (see z0int {name} -h)",
        )

    return p



def _cmd_backends(args: argparse.Namespace) -> int:
    """backends list|doctor|capabilities|eval — never import torch on list path."""
    from z0int.backends.registry import (
        backend_status,
        create_backend,
        get_backend_spec,
        list_backend_specs,
        register_builtin_backends,
    )

    cmd = args.backends_cmd
    if cmd == "list":
        register_builtin_backends()
        rows = []
        for spec in list_backend_specs():
            # Cheap health: factory must not load GPU; health(load=False) is FS only.
            try:
                h = spec.factory().health(load=False)
                rows.append(
                    {
                        "id": spec.id,
                        "kind": spec.kind,
                        "local": spec.local,
                        "configured": h.configured,
                        "ready": h.ready,
                        "model": h.model,
                        "detail": h.detail,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "id": spec.id,
                        "kind": spec.kind,
                        "local": spec.local,
                        "configured": False,
                        "ready": False,
                        "model": None,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
        payload = {"schema": "z0int.backends.v1", "backends": rows}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("id                 kind              ready  model")
            for r in rows:
                print(
                    f"{r['id']:<18} {r['kind']:<16} "
                    f"{'yes' if r['ready'] else 'no':<5} {r.get('model') or '-'}"
                )
                if r.get("detail"):
                    print(f"  {r['detail']}")
        return 0

    if cmd == "doctor":
        rows = backend_status(args.backend, load=bool(args.load))
        payload = {
            "schema": "z0int.backends.doctor.v1",
            "load": bool(args.load),
            "backends": rows,
        }
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            for r in rows:
                mark = "✓" if r.get("ready") else "○"
                print(f"{mark} {r['id']}: {r.get('detail')}")
                if r.get("checkpoint"):
                    print(f"  checkpoint: {r['checkpoint']}")
        return 0

    if cmd == "capabilities":
        spec = get_backend_spec(args.name)
        from dataclasses import asdict as _asdict

        backend = spec.factory()
        caps = _asdict(backend.capabilities)
        payload = {"schema": "z0int.backends.capabilities.v1", "id": spec.id, "capabilities": caps}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for k, v in caps.items():
                print(f"{k}: {v}")
        return 0

    if cmd == "eval":
        from pathlib import Path

        from z0int.backends.base import request_from_mapping, result_to_dict

        path = Path(args.input).expanduser()
        raw = json.loads(path.read_text(encoding="utf-8"))
        request = request_from_mapping(raw)
        backend = create_backend(args.backend)
        result = backend.evaluate(request)
        payload = result_to_dict(result)
        print(json.dumps(payload, indent=2, default=str))
        return 0

    if cmd == "bench":
        from pathlib import Path

        from z0int.backends.bench import run_bench

        out = run_bench(
            contract=args.contract,
            fixtures_path=Path(args.fixtures).expanduser() if args.fixtures else None,
            backend_filter=args.backend,
            capability_filter=args.capability,
            output_dir=Path(args.output).expanduser() if args.output else None,
            seed=args.seed,
            bootstrap_draws=args.bootstrap_draws,
        )
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print("z0int backends bench")
            print(f"  contract={args.contract}")
            print(f"  output={out.get('output_dir')}")
            print(f"  tokenomics={out.get('tokenomics_events')}")
            print(f"  raw={out.get('raw_jsonl')}")
            print(f"  summary={out.get('summary_json')}")
            print(f"  pareto={out.get('pareto_md')}")
            print(f"  parity_ok={out.get('parity_ok')}")
        return 0

    print(f"unknown backends command: {cmd}", file=sys.stderr)
    return 2



def _cmd_context(args: argparse.Namespace) -> int:
    from z0int.context_resolve import (
        InformationNeed,
        needs_from_mapping,
        resolve_context,
    )

    if args.context_cmd != "resolve":
        print(f"unknown context command: {args.context_cmd}", file=sys.stderr)
        return 2
    needs = []
    if args.input:
        raw = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
        needs.extend(needs_from_mapping(raw if isinstance(raw, dict) else {"needs": raw}))
    for i, path in enumerate(getattr(args, "path", None) or []):
        needs.append(InformationNeed(id=f"p{i}", description=path, kind="exact_path", path=path))
    packet = resolve_context(
        needs=needs or None,
        query=getattr(args, "query", None),
        task_id=getattr(args, "task_id", None),
        project_root=getattr(args, "project_root", None),
        allow_qmd=not bool(getattr(args, "no_qmd", False)),
        allow_memory=bool(getattr(args, "allow_memory", False)),
    )
    payload = packet.to_dict()
    if args.json or True:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not packet.unresolved_gaps else 0  # gaps are data, not process failure



def _cmd_task(args: argparse.Namespace) -> int:
    from pathlib import Path

    from z0int.task_loop import (
        PatchSpec,
        authorize_task,
        list_checkpoints,
        load_checkpoint,
        make_fixture_repo,
        resume_task,
        run_until,
        save_checkpoint,
    )

    def emit(obj: dict) -> None:
        if getattr(args, "json", False) or True:
            print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))

    cmd = args.task_cmd
    if cmd == "status":
        if args.task_id:
            cp = load_checkpoint(args.task_id)
            emit(cp.to_dict())
        else:
            emit({"tasks": list_checkpoints()})
        return 0
    if cmd == "authorize":
        cp = authorize_task(
            base_repo=args.repo,
            patch=PatchSpec(relative_path=args.path, find=args.find, replace=args.replace),
            requirement_paths=list(args.req or []),
            task_id=args.task_id,
        )
        emit(cp.to_dict())
        return 0
    if cmd == "run":
        cp = resume_task(args.task_id, until=args.until, allow_qmd=bool(getattr(args, "allow_qmd", False)))
        emit(cp.to_dict())
        # exit 0 always for data; verified flag is in payload
        return 0 if cp.verified_success is not False or cp.status != "failed" else 1
    if cmd == "fixture":
        root, patch = make_fixture_repo(Path(args.dir))
        cp = authorize_task(
            base_repo=root,
            patch=patch,
            requirement_paths=["REQUIREMENT.md", "app.py"],
            task_id=args.task_id,
        )
        cp = run_until(cp, until="verified", allow_qmd=False)
        emit(cp.to_dict())
        return 0 if cp.verified_success else 1
    print(f"unknown task command: {cmd}", file=sys.stderr)
    return 2



def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "as_json", False))

    if args.cmd == "doctor":
        return cmd_doctor(as_json=as_json)
    if args.cmd == "status":
        return cmd_status(as_json=as_json)
    if args.cmd == "context":
        return _cmd_context(args)
    if args.cmd == "task":
        return _cmd_task(args)
    if args.cmd == "backends":
        return _cmd_backends(args)

    if args.cmd == "onboard":
        return cmd_onboard(
            auto=bool(getattr(args, "auto", True)),
            force=bool(getattr(args, "force", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            sync_models=bool(getattr(args, "sync_models", False)),
            skip_evolution_lab=bool(getattr(args, "skip_evolution_lab", False)),
            as_json=as_json,
        )
    if args.cmd == "models":
        if args.models_cmd == "plan":
            return cmd_models_plan(as_json=as_json)
        if args.models_cmd == "sync":
            return cmd_models_sync(
                which=getattr(args, "which", "resident"),
                dry_run=bool(getattr(args, "dry_run", False)),
                as_json=as_json,
            )
    if args.cmd == "data":
        if args.data_cmd == "discover":
            return cmd_data_discover(as_json=as_json)
    if args.cmd == "receipt":
        if args.receipt_cmd == "emit":
            return cmd_receipt_emit(args=args)
        if args.receipt_cmd == "join":
            return cmd_receipt_join(args=args)
        if args.receipt_cmd == "close":
            return cmd_receipt_close(args=args)
        if args.receipt_cmd == "summary":
            return cmd_receipt_summary(as_json=as_json)
        if args.receipt_cmd == "scrub":
            return cmd_receipt_scrub(
                as_json=as_json,
                dry_run=bool(getattr(args, "dry_run", False)),
            )

    if args.cmd == "counterfactual":
        from .counterfactual import cmd_mine, cmd_summary

        if args.counterfactual_cmd == "mine":
            return cmd_mine(args=args, as_json=as_json)
        if args.counterfactual_cmd == "summary":
            return cmd_summary(args=args, as_json=as_json)
        if args.counterfactual_cmd == "worker-needed-ingest":
            from .replay.worker_needed import cmd_ingest

            return cmd_ingest(as_json=as_json, limit=int(getattr(args, "limit", 50) or 50))


    if args.cmd == "artifacts":
        from .artifacts import import_manifest, inspect_manifest, list_artifacts
        if args.artifacts_cmd == "inspect":
            out = inspect_manifest(args.manifest)
            _print(out, as_json=as_json)
            return 0 if out.get("ok") else 1
        if args.artifacts_cmd == "import":
            out = import_manifest(args.manifest, force=bool(getattr(args, "force", False)))
            _print(out, as_json=as_json)
            return 0 if out.get("ok") else 1
        if args.artifacts_cmd == "list":
            out = {"schema": "z0int.artifacts_list.v1", "artifacts": list_artifacts()}
            _print(out, as_json=as_json)
            return 0

    if args.cmd == "contrastive":
        from . import contrastive_evidence as ce
        import json as _json
        if args.contrastive_cmd == "fixture":
            fam = ce.example_project_status_family()
            _print(fam.to_dict(), as_json=True)
            return 0
        if args.contrastive_cmd == "eval":
            if getattr(args, "family_json", None):
                fam = ce.ContrastFamily.from_dict(_json.loads(Path(args.family_json).read_text(encoding="utf-8")))
            else:
                fam = ce.example_project_status_family()
            if getattr(args, "recipe_json", None):
                recipe = _json.loads(Path(args.recipe_json).read_text(encoding="utf-8"))
                out = ce.evaluate_recipe_on_family(fam, recipe)
            else:
                out = ce.evaluate_family(fam)
            if getattr(args, "store", False):
                path = ce.store_dependency(out["dependency"])
                out["dependency_path"] = str(path)
            _print(out, as_json=as_json)
            return 0 if out.get("full_pass") else 1
        if args.contrastive_cmd == "race":
            from .data_recipe_race import race_data_recipes

            if getattr(args, "families_jsonl", None):
                families = []
                for line in Path(args.families_jsonl).read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        families.append(ce.ContrastFamily.from_dict(_json.loads(line)))
            else:
                families = [ce.example_project_status_family()]
            recipe = None
            if getattr(args, "recipe_json", None):
                recipe = _json.loads(Path(args.recipe_json).read_text(encoding="utf-8"))
            out = race_data_recipes(families, recipe=recipe)
            _print(out, as_json=as_json)
            return 0

    if args.cmd == "context-state":
        from .capabilities import context_project_state as cps

        if args.context_state_cmd == "fixture":
            _print(cps.fixture_family().to_dict(), as_json=True)
            return 0
        if args.context_state_cmd == "compile":
            snap = _json.loads(Path(args.snapshot_json).read_text(encoding="utf-8"))
            if getattr(args, "store", False):
                out = cps.compile_and_store(snap)
            else:
                out = cps.compile_episode(snap)
            _print(out, as_json=as_json)
            return 0 if out.get("ok", True) else 1

    if args.cmd == "autoresearch":
        from .autoresearch import daemon as ar_daemon
        from .autoresearch.queue import enqueue_trace
        cmd = args.autoresearch_cmd
        if cmd == "status":
            _print(ar_daemon.status(), as_json=as_json)
            return 0
        if cmd == "pause":
            _print(ar_daemon.pause(), as_json=as_json)
            return 0
        if cmd == "resume":
            _print(ar_daemon.resume(), as_json=as_json)
            return 0
        if cmd == "run-once":
            _print(ar_daemon.run_once(), as_json=as_json)
            return 0
        if cmd == "report":
            _print(ar_daemon.report(), as_json=as_json)
            return 0
        if cmd == "daemon":
            mi = None if getattr(args, "forever", False) else int(getattr(args, "max_iterations", 10))
            _print(ar_daemon.run_daemon(poll_seconds=float(getattr(args, "poll_seconds", 5.0)), max_iterations=mi), as_json=as_json)
            return 0
        if cmd == "enqueue":
            vs = str(getattr(args, "verified_success", "true")).lower() in ("1", "true", "yes", "y")
            kind = getattr(args, "kind", None) or "context_policy"
            pl = {"kind": kind}
            out = enqueue_trace(
                args.trace_id,
                verified_success=True if vs else False,
                verifier_id=args.verifier_id,
                payload=pl,
            )
            _print(out, as_json=as_json)
            return 0 if out.get("ok") else 1
        if cmd == "research-once":
            from pathlib import Path
            from .autoresearch.research.pipeline import run_research_once
            el = getattr(args, "evolution_lab_root", None)
            out = run_research_once(
                driver_name=str(getattr(args, "driver", "agy")),
                evolution_lab_root=Path(el) if el else None,
                force_resources=bool(getattr(args, "force_resources", False)),
                skip_unit_tests=True,
            )
            _print(out, as_json=as_json)
            return 0 if out.get("ok") else 1

    if args.cmd == "kerdoios":
        from .kerdoios_export import export_observations
        if args.kerdoios_cmd == "export-observations":
            out = export_observations(since=getattr(args, "since", None), output=getattr(args, "output", None))
            _print(out, as_json=as_json)
            return 0

    if args.cmd == "os-context":
        from . import os_context
        from .specialists import next_operator

        if args.os_context_cmd == "import":
            db = Path(args.db).expanduser() if getattr(args, "db", None) else None
            if db is not None:
                out = os_context.import_from_db(db_path=db, limit=int(getattr(args, "limit", 50000) or 50000))
            else:
                out = os_context.import_via_cli(limit=int(getattr(args, "limit", 50000) or 50000))
            _print(out, as_json=as_json)
            return 0 if out.get("ok") else 1
        if args.os_context_cmd == "stats":
            out = os_context.stats()
            _print(out, as_json=as_json)
            return 0 if out.get("ok", True) else 1
        if args.os_context_cmd == "next-operator":
            out = next_operator.shadow_report()
            _print(out, as_json=as_json)
            return 0 if out.get("ok", True) else 1

    if args.cmd == "preflight":
        from .preflight import preflight_dict
        out = preflight_dict(args.prompt, capability_id=getattr(args, "capability_id", None))
        _print(out, as_json=as_json)
        return 0

    if args.cmd in ("routine", "cascade", "aodl", "repair", "abab"):
        rest = list(getattr(args, "module_argv", None) or [])
        # argparse REMAINDER keeps a leading "--" when users write: z0int routine -- compile ...
        if rest and rest[0] == "--":
            rest = rest[1:]
        # bare `z0int routine` / `z0int routine -h` → module help
        if not rest or rest in (["-h"], ["--help"]):
            rest = ["--help"]
        if args.cmd == "routine":
            from .routines import _main as _mod_main
        elif args.cmd == "cascade":
            from .cascade import _main as _mod_main
        elif args.cmd == "aodl":
            from .aodl import _main as _mod_main
        elif args.cmd == "repair":
            from .refinement import main as _mod_main
        else:
            from .abab import _main as _mod_main
        return int(_mod_main(rest))

    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
