"""SymPy identity check inside the isolated verifier sandbox only."""
from __future__ import annotations
import json
from council.verify.sandbox import run_python

def identity(left: str, right: str, *, timeout: float = 15):
    if max(len(left), len(right)) > 2000:
        raise ValueError("Identity expression too long")
    # Trusted wrapper, untrusted expressions passed as data and parsed IN sandbox.
    script = "import json\nfrom sympy import symbols, sympify, simplify\n" + (
        "x,y,z,n = symbols('x y z n')\n"
        "left, right = json.loads(" + repr(json.dumps([left, right])) + ")\n"
        "allowed = {'x':x, 'y':y, 'z':z, 'n':n}\n"
        "a,b = sympify(left, locals=allowed), sympify(right, locals=allowed)\n"
        "print(json.dumps({'pass': bool(simplify(a-b)==0)}))\n")
    return run_python(script, timeout=timeout)
