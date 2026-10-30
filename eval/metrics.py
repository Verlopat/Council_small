"""Bootstrap across tasks, not correlated repeated runs."""
from __future__ import annotations
import random
import statistics

def bootstrap_ci(deltas: list[float], n: int=10000, alpha: float=0.05,
                 seed: int=0) -> tuple[float,float,float]:
    if not deltas or n < 100 or not (0 < alpha < 1):
        raise ValueError("Invalid bootstrap request")
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(deltas, k=len(deltas)))
                   for _ in range(n))
    lo = means[int(n*alpha/2)]
    hi = means[min(n-1, int(n*(1-alpha/2)))]
    return statistics.fmean(deltas), lo, hi

def earns_its_place(deltas: list[float], *, higher_is_better: bool=True) -> bool:
    _, lo, hi = bootstrap_ci(deltas)
    return lo > 0 if higher_is_better else hi < 0
