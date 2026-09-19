"""Decision-backend Pareto benchmark harness (decision-capability-v1)."""

from .contract import BENCH_CONTRACT, CAPABILITIES, ROSTER_CANDIDATES
from .runner import run_bench

__all__ = ["BENCH_CONTRACT", "CAPABILITIES", "ROSTER_CANDIDATES", "run_bench"]
