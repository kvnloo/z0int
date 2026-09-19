"""Hardware-aware model planning and optional download.

Deterministic: never invent unpinned HF IDs. Sync is opt-in.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    root = _repo_root()
    if path is None:
        # Prefer JSON twin (no PyYAML). YAML remains human source-of-truth.
        candidates = [
            root / "manifests" / "models.z0int.json",
            root / "manifests" / "models.yaml",
            root / "manifests" / "models.json",
        ]
    else:
        candidates = [path]
    for cand in candidates:
        if not cand.is_file():
            continue
        text = cand.read_text(encoding="utf-8")
        if cand.suffix in {".yaml", ".yml"}:
            if yaml is None:
                continue
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        data = json.loads(text)
        if cand.name == "models.json" and isinstance(data.get("models"), list):
            return _legacy_json_to_manifest(data)
        return data if isinstance(data, dict) else {}
    raise FileNotFoundError("no models manifest found under manifests/")


def _legacy_json_to_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for row in raw.get("models") or []:
        role = str(row.get("role") or "unknown")
        models[role] = {
            "hf": row.get("source"),
            "revision": row.get("revision"),
            "dtype": row.get("dtype"),
            "min_vram_gb": 10,
            "roles": [role],
        }
    return {"schema": "z0int.models.v1", "models": models, "policies": {}}


def detect_vram_gb() -> float | None:
    """Best-effort VRAM detection; None if no GPU. nvidia-smi memory.total is MiB."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
        vals = [float(x.strip()) for x in out.strip().splitlines() if x.strip()]
        if not vals:
            return None
        return max(vals) / 1024.0  # MiB → GiB
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def detect_gpu_name() -> str | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            timeout=5,
        )
        line = out.strip().splitlines()[0].strip() if out.strip() else ""
        return line or None
    except (subprocess.SubprocessError, OSError):
        return None


def select_policy(vram_gb: float | None, policies: dict[str, Any]) -> str:
    if vram_gb is None or vram_gb <= 0:
        return "cpu_only" if "cpu_only" in policies else "twelve_gb"
    if vram_gb >= 20 and "high_vram" in policies:
        return "high_vram"
    if vram_gb >= 8 and "twelve_gb" in policies:
        return "twelve_gb"
    return "cpu_only" if "cpu_only" in policies else "twelve_gb"


def decision_roster(*, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Canonical Jev/System-One decision backend roster from manifests/models.*."""
    man = manifest or load_manifest()
    roster = man.get("decision_roster") or {}
    candidates = list(roster.get("candidates") or [])
    models = man.get("models") or {}
    entries = {
        cid: {
            "family": (models.get(cid) or {}).get("family"),
            "hf": (models.get(cid) or {}).get("hf"),
            "revision": (models.get(cid) or {}).get("revision"),
            "type": (models.get(cid) or {}).get("type", "hf"),
            "platforms": (models.get(cid) or {}).get("platforms"),
            "license": (models.get(cid) or {}).get("license"),
            "commercial_use": (models.get(cid) or {}).get("commercial_use"),
            "optional": (models.get(cid) or {}).get("optional"),
            "roles": (models.get(cid) or {}).get("roles") or [],
        }
        for cid in candidates
        if cid in models
    }
    return {
        "schema": roster.get("schema") or "z0int.decision_roster.v1",
        "description": roster.get("description"),
        "candidates": candidates,
        "entries": entries,
    }


def plan_models(*, manifest: dict[str, Any] | None = None, vram_gb: float | None = None) -> dict[str, Any]:
    man = manifest or load_manifest()
    models = man.get("models") or {}
    policies = man.get("policies") or {}
    if vram_gb is None:
        vram_gb = detect_vram_gb()
    policy_name = select_policy(vram_gb, policies)
    policy = policies.get(policy_name) or {}
    resident = list(policy.get("resident") or [])
    on_demand = list(policy.get("on_demand") or [])

    def ok(mid: str) -> bool:
        m = models.get(mid) or {}
        if m.get("type") == "generated":
            return True
        need = float(m.get("min_vram_gb") or 0)
        if vram_gb is None:
            return m.get("type") == "generated"
        return need <= float(vram_gb) + 0.5

    resident = [m for m in resident if m in models and ok(m)]
    on_demand = [m for m in on_demand if m in models and ok(m)]
    never = policy.get("never_coreside") or []
    return {
        "schema": "z0int.models_plan.v1",
        "gpu_name": detect_gpu_name() if vram_gb not in (None, 0.0) or vram_gb is None else None,
        "vram_gb": vram_gb,
        "policy": policy_name,
        "resident": resident,
        "on_demand": on_demand,
        "never_coreside": never,
        "models": {
            mid: {
                "hf": (models[mid] or {}).get("hf"),
                "revision": (models[mid] or {}).get("revision"),
                "type": (models[mid] or {}).get("type", "hf"),
                "roles": (models[mid] or {}).get("roles") or [],
                "min_vram_gb": (models[mid] or {}).get("min_vram_gb"),
                "local_dir": (
                    str(managed_model_dir(mid))
                    if (models[mid] or {}).get("type") == "hf_bundle"
                    else None
                ),
                "present": model_present(mid, models[mid] or {}),
            }
            for mid in models
        },
        "recommendation": _human(policy_name, resident, on_demand, never),
    }


def _human(policy: str, resident: list[str], on_demand: list[str], never: list) -> str:
    lines = [
        f"policy={policy}",
        f"resident: {', '.join(resident) or '(none)'}",
        f"on-demand: {', '.join(on_demand) or '(none)'}",
    ]
    if never:
        lines.append(f"do not co-reside: {never}")
    return "; ".join(lines)


def model_cached(hf_id: str, revision: str | None = None) -> bool:
    """True if huggingface hub cache appears to hold the revision (best-effort)."""
    hf_home = Path.home() / ".cache" / "huggingface" / "hub"
    if not hf_home.is_dir():
        return False
    slug = "models--" + hf_id.replace("/", "--")
    root = hf_home / slug
    if not root.is_dir():
        return False
    if not revision:
        return True
    refs = root / "refs"
    if refs.is_dir():
        for p in refs.iterdir():
            try:
                if p.read_text(encoding="utf-8").strip() == revision:
                    return True
            except OSError:
                continue
    return (root / "snapshots" / revision).is_dir()




def managed_model_dir(model_id: str) -> Path:
    """Canonical managed bundle path under ~/.z0int/models/<id>/."""
    from . import paths

    return paths.home() / "models" / model_id


def bundle_complete(model_id: str, meta: dict[str, Any] | None = None) -> bool:
    """True when a managed hf_bundle has the required NanoJev-style layout."""
    meta = meta or {}
    root = managed_model_dir(model_id)
    # Prefer NanoJev validator when available; fall back to allow_patterns files.
    try:
        from z0int.backends.nanojev_runtime import validate_checkpoint_dir

        return root.is_dir() and not validate_checkpoint_dir(root)
    except Exception:
        patterns = meta.get("allow_patterns") or []
        if not root.is_dir() or not patterns:
            return False
        for pat in patterns:
            if pat.endswith("/*"):
                if not (root / pat[:-2]).is_dir():
                    return False
            elif not (root / pat).is_file():
                return False
        return True


def model_present(model_id: str, meta: dict[str, Any]) -> bool:
    """Whether weights appear available for plan/sync status."""
    mtype = meta.get("type") or "hf"
    if mtype == "generated":
        return True
    if mtype == "hf_bundle":
        return bundle_complete(model_id, meta)
    hf = meta.get("hf")
    rev = meta.get("revision")
    if not hf:
        return False
    return model_cached(str(hf), str(rev) if rev else None)

def sync_models(
    *,
    plan: dict[str, Any] | None = None,
    which: str = "resident",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Download planned HF models. which=resident|on_demand|all."""
    plan = plan or plan_models()
    man = load_manifest()
    models = man.get("models") or {}
    ids: list[str] = []
    if which in ("resident", "all"):
        ids.extend(plan.get("resident") or [])
    if which in ("on_demand", "all"):
        ids.extend(plan.get("on_demand") or [])
    seen: set[str] = set()
    ordered: list[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    results: list[dict[str, Any]] = []
    for mid in ordered:
        meta = models.get(mid) or {}
        mtype = meta.get("type") or "hf"
        if mtype == "generated":
            results.append({"id": mid, "status": "skip_generated"})
            continue
        hf = meta.get("hf")
        rev = meta.get("revision")
        if not hf or not rev:
            results.append({"id": mid, "status": "missing_pin"})
            continue
        if mtype == "hf_bundle":
            local_dir = managed_model_dir(mid)
            if bundle_complete(mid, meta):
                results.append(
                    {
                        "id": mid,
                        "status": "cached",
                        "hf": hf,
                        "revision": rev,
                        "path": str(local_dir),
                        "type": mtype,
                    }
                )
                continue
            if dry_run:
                results.append(
                    {
                        "id": mid,
                        "status": "would_download",
                        "hf": hf,
                        "revision": rev,
                        "path": str(local_dir),
                        "type": mtype,
                        "allow_patterns": list(meta.get("allow_patterns") or []),
                    }
                )
                continue
            try:
                from huggingface_hub import snapshot_download

                local_dir.mkdir(parents=True, exist_ok=True)
                path = snapshot_download(
                    repo_id=str(hf),
                    revision=str(rev),
                    local_dir=str(local_dir),
                    allow_patterns=(list(meta.get("allow_patterns")) if meta.get("allow_patterns") else None),
                )
                results.append(
                    {
                        "id": mid,
                        "status": "downloaded",
                        "hf": hf,
                        "revision": rev,
                        "path": str(path),
                        "type": mtype,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "id": mid,
                        "status": "error",
                        "hf": hf,
                        "revision": rev,
                        "error": str(exc),
                        "type": mtype,
                    }
                )
            continue
        if model_cached(str(hf), str(rev)):
            results.append({"id": mid, "status": "cached", "hf": hf, "revision": rev})
            continue
        if dry_run:
            results.append({"id": mid, "status": "would_download", "hf": hf, "revision": rev})
            continue
        try:
            from huggingface_hub import snapshot_download

            path = snapshot_download(repo_id=str(hf), revision=str(rev))
            results.append(
                {"id": mid, "status": "downloaded", "hf": hf, "revision": rev, "path": path}
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {"id": mid, "status": "error", "hf": hf, "revision": rev, "error": str(exc)}
            )
    return {"schema": "z0int.models_sync.v1", "which": which, "dry_run": dry_run, "results": results}
