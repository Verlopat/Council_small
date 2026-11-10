"""Author-code versus author-answer consistency, never independent proof.

Untrusted Python runs ONLY in the fail-closed bubblewrap verifier. A passing
comparison means that the author's code prints its own claimed scalar.
"""
from __future__ import annotations
import ast
from decimal import Decimal,InvalidOperation
from council.verify.sandbox import run_python
from council.final_answers import normalize_answer


PRELUDE="import json, math, itertools, functools, fractions\n"


def _canonical(value:object)->str|None:
    if type(value) is bool:
        return "yes" if value else "no"
    if type(value) in (int,float,Decimal):
        try:
            num=Decimal(str(value))
            return format(num.normalize(),"f") if num.is_finite() else None
        except (InvalidOperation,ValueError):
            return None
    if not isinstance(value,str):
        return None
    scalar=normalize_answer(value)
    if scalar is None:
        return None
    if scalar.lower() in {"yes","true"}:
        return "yes"
    if scalar.lower() in {"no","false"}:
        return "no"
    try:
        num=Decimal(scalar)
        return format(num.normalize(),"f") if num.is_finite() else None
    except InvalidOperation:
        return None


def recompute_answer(code:str,claimed:str,*,timeout:float=8)->tuple[str,str]:
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
    return ("pass" if computed==want else "fail"),("printed="+computed[:90])
