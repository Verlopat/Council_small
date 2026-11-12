"""Author-code versus author-answer consistency, never independent proof.

Untrusted Python runs ONLY in the fail-closed bubblewrap verifier. A passing
comparison means that the author's code prints its own claimed scalar.
"""
from __future__ import annotations
import ast
from fractions import Fraction
from council.verify.sandbox import run_python
from council.final_answers import canonical_scalar


PRELUDE="import json, math, itertools, functools, fractions\n"


# Keep author-code normalization identical to executed-family voting.
_canonical=canonical_scalar

def recompute_answer(code:str,claimed:str,*,timeout:float=8,
                     capture:dict|None=None)->tuple[str,str]:
    """Return (pass|fail|error,detail); no run outside bubblewrap."""
    if not isinstance(code,str) or not code.strip():
        return "error","missing_code"
    want=_canonical(claimed)
    if want is None:
        return "error","invalid_claimed_scalar"
    result=run_python(PRELUDE+code+"\n",timeout=timeout,
                      expect_pass_json=False)
    if result.outcome!="ok":
        return "error",result.detail
    lines=result.stdout.strip().splitlines()
    if not lines:
        return "error","no_value_printed"
    last=lines[-1].strip()
    if len(last)>1600:
        return "error","printed_value_too_large"
    try:
        output=ast.literal_eval(last)
    except (ValueError,SyntaxError,MemoryError,RecursionError):
        output=last
    if isinstance(output,dict):
        output=output.get("answer",output.get("result"))
    computed=_canonical(output)
    if computed is None:
        return "error","printed_value_not_scalar"
    if capture is not None:
        capture["value"]=computed
    same = computed == want
    if not same and computed not in {"yes", "no"} and want not in {"yes", "no"}:
        # Preserve exact integer equality; tolerate only decimal round-off.
        if computed != "no solution" and want != "no solution":
            a, b = Fraction(computed), Fraction(want)
            if a.denominator != 1 or b.denominator != 1:
                tolerance = max(Fraction("1e-12"),
                                Fraction("2e-15") * max(abs(a), abs(b)))
                same = abs(a-b) <= tolerance
    return ("pass" if same else "fail"), ("printed="+computed[:90])
