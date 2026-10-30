"""Explicitly distinguish self-consistency from best-of-N selection."""
from __future__ import annotations
from collections import Counter
from typing import Callable, TypeVar

T = TypeVar("T")

def self_consistency(samples: list[str]) -> str:
    if not samples:
        raise ValueError("No samples")
    # Ties broken deterministically by original order.
    counts = Counter(samples)
    return max(dict.fromkeys(samples), key=lambda x: counts[x])

def best_of_n(samples: list[T], score: Callable[[T], float]) -> T:
    if not samples:
        raise ValueError("No samples")
    return max(samples, key=score)
