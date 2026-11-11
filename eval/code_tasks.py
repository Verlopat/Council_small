"""Score model-written Python implementations ONLY inside fail-closed bwrap.

Hidden examples never enter model prompts, Council calls, or a best-of-N
selection mechanism. No host execution fallback is permitted.
"""
from __future__ import annotations
import json
import re
from council.verify.sandbox import run_python,available


FENCE=re.compile(r"(?ms)^(?:\x60){3}(?:python|py)?\s*\n(.*?)^(?:\x60){3}\s*$")
FUNCTION=re.compile(r"(?m)^(?:\s*\[S\d+\]\s*)?def\s+f\s*\(\s*xs\s*\)\s*:")


def extract_function_source(response:object) -> str | None:
    if not isinstance(response,str) or len(response)>65536:
        return None
    for match in FENCE.finditer(response):
        code=match.group(1).strip()
        if FUNCTION.search(code):
            return code
    match=FUNCTION.search(response)
    if match:
        lines=response[match.start():].splitlines()
        source=[re.sub(r"^\s*\[S\d+\]\s*","",lines[0])]
        for line in lines[1:]:
            if line.strip() and not line.startswith((" ","\t")):
                break
            source.append(line)
        return "\n".join(source).strip()
    return None


def hidden_case_outcome(response:object,hidden_spec:dict) -> str:
    """Return pass/fail/error/no_code/unavailable, not scientific proof."""
    if not available():
        return "unavailable"
    code=extract_function_source(response)
    if code is None:
        return "no_code"
    cases=hidden_spec.get("cases") if isinstance(hidden_spec,dict) else None
    if (not isinstance(cases,list) or not 1<=len(cases)<=30 or
            any(not isinstance(row,dict)
                or not isinstance(row.get("input"),list)
                or any(type(x) is not int for x in row["input"])
                or type(row.get("expected")) is not int for row in cases)):
        return "error"
    fixtures=json.dumps(cases,ensure_ascii=True,separators=(",",":"))
    harness=(
        "\n\nimport json as __council_json\n"
        f"__council_cases=__council_json.loads({fixtures!r})\n"
        "__council_ok=True\n"
        "for __case in __council_cases:\n"
        "    try:\n"
        "        __got=f(__case['input'])\n"
        "        if type(__got) is not int or __got != __case['expected']:\n"
        "            __council_ok=False\n"
        "    except Exception:\n"
        "        __council_ok=False\n"
        "print(__council_json.dumps({'pass':__council_ok}))\n")
    outcome=run_python(code+harness,timeout=8).outcome
    return outcome if outcome in {"pass","fail"} else "error"


def public_case_output(response:object,prompt:str) -> str | None:
    """Execute f(xs) on an explicitly public literal input, never hidden gold."""
    import ast
    code=extract_function_source(response)
    match=re.search(r'\bxs\s*=\s*(\[[^\[\]]{0,2000}\])',prompt)
    if code is None or match is None or not available():
        return None
    try:
        values=ast.literal_eval(match.group(1))
    except (ValueError,SyntaxError,RecursionError):
        return None
    if (not isinstance(values,list) or len(values)>100
            or any(type(x) is not int or abs(x)>10**12 for x in values)):
        return None
    harness=("\n\nimport json as __council_json\n"
             f"__council_value=f({values!r})\n"
             "if type(__council_value) is not int:\n"
             "    raise TypeError('public result must be an integer')\n"
             "print(__council_json.dumps({'result':__council_value}))\n")
    result=run_python(code+harness,timeout=8,expect_pass_json=False)
    if result.outcome!='ok':
        return None
    try:
        value=json.loads(result.stdout.strip().splitlines()[-1])['result']
    except (ValueError,IndexError,TypeError,KeyError):
        return None
    return str(value) if type(value) is int else None
