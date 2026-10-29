"""Optional formal/security tool adapters. Fail closed; all proof text stays inside bwrap.

An accepted proof checks only the submitted formal statement, not the fidelity
of its translation from an informal cryptography claim.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from council.verify.sandbox import run_python

@dataclass(frozen=True)
class DomainCheck:
    outcome:str
    tool:str
    limitation:str
    trace:str

_TOOL_ARGS={
    "lean":("lean","/work/input.lean"),
    "proverif":("proverif","/work/input.pv"),
    "tamarin":("tamarin-prover","--prove","/work/input.spthy"),
}
_EXTENSIONS={"lean":"lean","proverif":"pv","tamarin":"spthy"}

def check(tool:str,source:str,*,timeout:float=30)->DomainCheck:
    if tool not in _TOOL_ARGS:
        raise ValueError("Unsupported proof assistant")
    if not isinstance(source,str) or not source.strip() or len(source)>65000:
        raise ValueError("Invalid proof source")
    # Never certify admitted proof holes; declared axioms are assumptions, not
    # an unconditional theorem. Source must still be reviewed by a human.
    lowered=source.lower()
    if tool=="lean" and any(marker in lowered for marker in ("sorry","admit")):
        return DomainCheck("inconclusive",tool,"Admitted proof hole","")
    command=list(_TOOL_ARGS[tool])
    extension=_EXTENSIONS[tool]
    code=("import subprocess, shutil, pathlib, json\n"
          "binary="+repr(command[0])+"\n"
          "source="+repr(source)+"\n"
          "available=shutil.which(binary)\n"
          "path=pathlib.Path('/work/input."+extension+"')\n"
          "path.write_text(source,encoding='utf-8')\n"
          "if not available:\n"
          " print(json.dumps({'pass': False, 'missing': True}))\n"
          "else:\n"
          " p=subprocess.run("+repr(command)+",stdout=subprocess.PIPE,"
          " stderr=subprocess.PIPE,text=True,timeout="+repr(max(1.0,timeout-2))+
          ")\n"
          " stdout=p.stdout.lower()\n"
          " confirmed=(p.returncode==0)\n"
          " if binary=='tamarin-prover':\n"
          "  confirmed=confirmed and 'verified' in stdout and 'falsified' not in stdout\n"
          " if binary=='proverif':\n"
          "  confirmed=confirmed and 'result' in stdout and 'is true' in stdout\n"
          " print(json.dumps({'pass': bool(confirmed)}))\n")
    result=run_python(code,timeout=timeout)
    return DomainCheck(result.outcome,tool,
                       "Formal tool output only; assumptions and claim correspondence need checking",
                       result.detail)
