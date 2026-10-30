"""Offline deployment checks. No API calls and no execution without sandbox.

Use on the actual target machine before enabling model-generated checks.
A passing preflight is necessary, not a security audit.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys

from council.verify.sandbox import available, run_python

@dataclass(frozen=True)
class Check:
    status: str
    reason: str

def environment_report() -> dict[str, Check]:
    report = {}
    report["python"] = Check(
        "pass" if sys.version_info >= (3,11) else "fail",
        "Python 3.11+ required")
    report["bubblewrap"] = Check(
        "available" if available() else "unavailable",
        "Network-isolated sandbox is mandatory for untrusted generated code")
    try:
        import sympy
        report["sympy"] = Check("available", "SymPy import works in host environment; sandbox still needs checking")
    except ImportError:
        report["sympy"] = Check("unavailable", "Install optional SymPy package")
    try:
        import z3
        report["z3"] = Check("available", "Z3 import works in host environment; sandbox still needs checking")
    except ImportError:
        report["z3"] = Check("unavailable", "Install optional z3-solver package")
    return report

def sandbox_report() -> dict[str, Check]:
    if not available():
        return {"sandbox":Check("fail", "bubblewrap is not available; no unsafe host fallback")}
    checks = {
        "execution": """import json
print(json.dumps({"pass": 6 * 7 == 42}))
""",
        "network_isolation": """import json, socket
denied = False
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.connect(("1.1.1.1", 53))
    except OSError:
        denied = True
    finally:
        sock.close()
except OSError:
    denied = True
print(json.dumps({"pass": denied}))
""",
        "host_home_isolation": """import json, os, pathlib
home = pathlib.Path("/home")
visible = []
if home.exists():
    try:
        visible = [p.name for p in home.iterdir()]
    except OSError:
        visible = []
print(json.dumps({"pass": not visible}))
""",
        "environment_isolation": """import json, os
print(json.dumps({"pass": not any(key.endswith("_API_KEY") or
    key in ("CLOUDFLARE_API_TOKEN", "COHERE_API_KEY", "OLLAMA_API_KEY")
    for key in os.environ)}))
""",
    }
    return {name: Check("pass" if (result:=run_python(source,timeout=6)).outcome == "pass"
                         else "fail", result.detail)
            for name, source in checks.items()}

def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Verify safe local Council prerequisites without API requests")
    parser.add_argument("--json", action="store_true")
    args=parser.parse_args(argv)
    report={**environment_report(), **sandbox_report()}
    payload={k:asdict(v) for k,v in report.items()}
    print(json.dumps(payload, indent=2))
    return 1 if any(v.status=="fail" for v in report.values()) else 0

if __name__=="__main__":
    raise SystemExit(main())
