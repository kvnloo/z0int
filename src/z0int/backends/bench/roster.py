"""Map manifest roster candidates to runnable DecisionBackend adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from z0int.models_mgmt import decision_roster, load_manifest

from ..base import DecisionBackend
from .contract import ROSTER_CANDIDATES

StatusKind = Literal["available", "unavailable", "unsupported"]


@dataclass(frozen=True)
class CandidateStatus:
    candidate_id: str
    status: StatusKind
    reason: str | None
    backend_impl: str | None
    commercial_use: bool | None
    platforms: tuple[str, ...]
    license: str | None
    optional: bool
    family: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "reason": self.reason,
            "backend_impl": self.backend_impl,
            "commercial_use": self.commercial_use,
            "platforms": list(self.platforms),
            "license": self.license,
            "optional": self.optional,
            "family": self.family,
        }


def _meta(candidate_id: str) -> dict[str, Any]:
    roster = decision_roster()
    return dict(roster.get("entries", {}).get(candidate_id) or {})


def _commercial(meta: dict[str, Any]) -> bool | None:
    if meta.get("commercial_use") is not None:
        return bool(meta["commercial_use"])
    lic = str(meta.get("license") or "").lower()
    if "nc" in lic or lic.startswith("cc-by-nc"):
        return False
    if lic in ("apache-2.0", "mit", "bsd-3-clause"):
        return True
    return None


def probe_candidate(candidate_id: str) -> CandidateStatus:
    if candidate_id not in ROSTER_CANDIDATES:
        return CandidateStatus(
            candidate_id=candidate_id,
            status="unsupported",
            reason=f"not in decision roster ({', '.join(ROSTER_CANDIDATES)})",
            backend_impl=None,
            commercial_use=None,
            platforms=(),
            license=None,
            optional=False,
            family=None,
        )
    meta = _meta(candidate_id)
    platforms = tuple(str(x) for x in (meta.get("platforms") or []))
    commercial = _commercial(meta)
    optional = bool(meta.get("optional"))
    family = meta.get("family")
    mtype = str(meta.get("type") or "hf")

    if candidate_id == "reflex":
        return CandidateStatus(
            candidate_id=candidate_id,
            status="unavailable",
            reason="browser_app; no headless DecisionBackend adapter for bench",
            backend_impl=None,
            commercial_use=commercial,
            platforms=platforms or ("webgpu", "browser"),
            license=meta.get("license"),
            optional=True,
            family=family,
        )
    if candidate_id == "local_mb":
        return CandidateStatus(
            candidate_id=candidate_id,
            status="unavailable",
            reason="generated mushroom_body specialist; no typed DecisionBackend adapter yet",
            backend_impl=None,
            commercial_use=True,
            platforms=("local",),
            license=None,
            optional=False,
            family=family,
        )
    if candidate_id == "laya_421m":
        from ..laya import LayaBackend

        try:
            backend = LayaBackend.for_manifest_id(candidate_id)
            health = backend.health(load=False)
            if health.ready:
                return CandidateStatus(
                    candidate_id=candidate_id,
                    status="available",
                    reason=None,
                    backend_impl="laya",
                    commercial_use=True,
                    platforms=platforms or ("cpu", "mps", "cuda"),
                    license=meta.get("license") or "apache-2.0",
                    optional=optional,
                    family=family,
                )
            return CandidateStatus(
                candidate_id=candidate_id,
                status="unavailable",
                reason=health.detail or "checkpoint not ready",
                backend_impl="laya",
                commercial_use=True,
                platforms=platforms or ("cpu", "mps", "cuda"),
                license=meta.get("license") or "apache-2.0",
                optional=optional,
                family=family,
            )
        except Exception as exc:  # noqa: BLE001
            return CandidateStatus(
                candidate_id=candidate_id,
                status="unavailable",
                reason=f"{type(exc).__name__}: {exc}",
                backend_impl="laya",
                commercial_use=True,
                platforms=platforms or ("cpu", "mps", "cuda"),
                license=meta.get("license") or "apache-2.0",
                optional=optional,
                family=family,
            )

    if candidate_id in ("decider_2b", "system_one_4b"):
        note = "manifest pin only; DecisionBackend adapter not implemented"
        if candidate_id == "system_one_4b":
            note += " (CC-BY-NC-4.0 — non-commercial)"
        return CandidateStatus(
            candidate_id=candidate_id,
            status="unavailable",
            reason=note,
            backend_impl=None,
            commercial_use=commercial,
            platforms=platforms,
            license=meta.get("license"),
            optional=optional,
            family=family,
        )

    if candidate_id == "nanojev_06b":
        from ..registry import register_builtin_backends

        register_builtin_backends()
        from ..nanojev import NanoJevBackend

        try:
            backend = NanoJevBackend.from_config()
            health = backend.health(load=False)
            if health.ready:
                return CandidateStatus(
                    candidate_id=candidate_id,
                    status="available",
                    reason=None,
                    backend_impl="nanojev",
                    commercial_use=True,
                    platforms=platforms or ("cuda",),
                    license=meta.get("license"),
                    optional=False,
                    family=family,
                )
            return CandidateStatus(
                candidate_id=candidate_id,
                status="unavailable",
                reason=health.detail or "checkpoint not ready",
                backend_impl="nanojev",
                commercial_use=True,
                platforms=platforms or ("cuda",),
                license=meta.get("license"),
                optional=False,
                family=family,
            )
        except Exception as exc:  # noqa: BLE001
            return CandidateStatus(
                candidate_id=candidate_id,
                status="unavailable",
                reason=f"{type(exc).__name__}: {exc}",
                backend_impl="nanojev",
                commercial_use=True,
                platforms=platforms or ("cuda",),
                license=meta.get("license"),
                optional=False,
                family=family,
            )

    if candidate_id in ("openjev_06b", "openjev_4b"):
        from ..openjev_direct import OpenJevDirectBackend

        try:
            backend = OpenJevDirectBackend.for_manifest_id(candidate_id)
            health = backend.health(load=False)
            if health.ready:
                return CandidateStatus(
                    candidate_id=candidate_id,
                    status="available",
                    reason=None,
                    backend_impl="openjev_direct",
                    commercial_use=True,
                    platforms=platforms or ("cuda", "mps"),
                    license=meta.get("license"),
                    optional=optional,
                    family=family,
                )
            return CandidateStatus(
                candidate_id=candidate_id,
                status="unavailable",
                reason=health.detail or "weights not cached",
                backend_impl="openjev_direct",
                commercial_use=True,
                platforms=platforms or ("cuda", "mps"),
                license=meta.get("license"),
                optional=optional,
                family=family,
            )
        except Exception as exc:  # noqa: BLE001
            return CandidateStatus(
                candidate_id=candidate_id,
                status="unavailable",
                reason=f"{type(exc).__name__}: {exc}",
                backend_impl="openjev_direct",
                commercial_use=True,
                platforms=platforms,
                license=meta.get("license"),
                optional=optional,
                family=family,
            )

    return CandidateStatus(
        candidate_id=candidate_id,
        status="unsupported",
        reason=f"unknown roster type {mtype!r}",
        backend_impl=None,
        commercial_use=commercial,
        platforms=platforms,
        license=meta.get("license"),
        optional=optional,
        family=family,
    )


def create_backend_for_candidate(candidate_id: str) -> DecisionBackend:
    status = probe_candidate(candidate_id)
    if status.status != "available":
        raise RuntimeError(status.reason or f"{candidate_id} not available")
    if candidate_id == "nanojev_06b":
        from ..nanojev import NanoJevBackend

        return NanoJevBackend.from_config()
    if candidate_id == "laya_421m":
        from ..laya import LayaBackend

        return LayaBackend.for_manifest_id(candidate_id)
    if candidate_id in ("openjev_06b", "openjev_4b"):
        from ..openjev_direct import OpenJevDirectBackend

        return OpenJevDirectBackend.for_manifest_id(candidate_id)
    raise RuntimeError(f"no factory for {candidate_id}")


def roster_adapter_table() -> list[dict[str, Any]]:
    return [probe_candidate(cid).to_dict() for cid in ROSTER_CANDIDATES]
