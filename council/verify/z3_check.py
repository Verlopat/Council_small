"""SMT counterexample search for explicitly supplied arithmetic expression assertions."""
from __future__ import annotations
import json
from council.verify.sandbox import run_python

def unsatisfiable(assertions: list[str], *, timeout: float = 10):
    if not assertions or len(assertions) > 30 or sum(map(len, assertions)) > 4000:
        raise ValueError("Bad assertions")
    # No arbitrary eval: parse the constrained SMT-LIB2 script through Z3.
    smt = "\n".join(assertions)
    wrapper = ("import json\nfrom z3 import Solver, unsat\n"
               "script=" + repr(smt) + "\n"
               "solver=Solver()\nsolver.from_string(script)\n"
               "print(json.dumps({'pass': bool(solver.check()==unsat)}))\n")
    return run_python(wrapper, timeout=timeout)
