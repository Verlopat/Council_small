"""Numeric mutants and conservative discrimination testing."""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")

def numeric_mutants(answer: str) -> list[str]:
    match = NUMBER.search(answer)
    if match is None:
        return []
    value = Decimal(match.group())
    values = {value + 1, value - 1, -value, value + Decimal("0.5")}
    return sorted({
        answer[:match.start()] + str(candidate) + answer[match.end():]
        for candidate in values if candidate != value
    })

def discriminates(run_check, original: str, mutants: list[str]) -> bool:
    """A pass for any mutant is evidence the check is insufficient.

    Exceptions and errors are *not* proof of discrimination.
    """
    if not mutants or run_check(original) != "pass":
        return False
    return all(run_check(mutant) == "fail" for mutant in mutants)
