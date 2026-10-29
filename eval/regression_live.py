"""Explicitly opt-in, scored weekly provider regression, no paid fallthrough.

Model names are not proof of unchanged weights. Score the same 20 known tasks
against every configured endpoint, compare aggregate scores and inspect drift.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import os
from council.families import FAMILIES
from council.transport import FamilyTransport
from model_router import Candidate, Router
from eval.regression_probe import make,compare,Probe
from answer_validation import matches_expected

def fixed_tasks()->list[tuple[str,str,str]]:
    return [(f"probe-{i:02d}",f"Compute {i+11} * {i+19}. Answer only with the integer.",
             str((i+11)*(i+19))) for i in range(20)]

def candidates():
    seen=set()
    for family in FAMILIES.values():
        for endpoint in family.endpoints:
            key=(endpoint.provider,endpoint.model)
            if key not in seen:
                seen.add(key)
                yield family.name,endpoint

def inspect(*,max_requests:int):
    if not 1<=max_requests<=1000:
        raise ValueError("Unsafe request bound")
    router=Router(timeout=30)
    rows=[]
    attempts=0
    for family,endpoint in candidates():
        if not FamilyTransport._eligible(endpoint.provider):
            continue
        selected=Candidate(endpoint.provider,endpoint.model)
        try:
            eligible=router.expand(selected,set())
        except Exception:
            continue
        if not eligible or eligible[0].model!=endpoint.model:
            continue
        for task_id,question,expected in fixed_tasks():
            if attempts>=max_requests:
                return rows
            attempts+=1
            try:
                actual=router.generate(selected,question,max_output_tokens=512)
                score=1.0 if matches_expected(actual,expected) else 0.0
            except Exception:
                actual=""
                score=0.0
            p=make(family,endpoint.model,task_id,actual,score)
            rows.append(p)
    return rows

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--confirm-free",action="store_true")
    p.add_argument("--max-requests",type=int,default=20)
    p.add_argument("--out",type=Path,default=Path("runs")/"regression.jsonl")
    p.add_argument("--previous",type=Path)
    args=p.parse_args(argv)
    if not 1<=args.max_requests<=1000:p.error("Invalid request cap")
    planned=sum(20 for _ in candidates())
    if not args.confirm_free:
        print(json.dumps({"mode":"plan_only","requests_if_unlimited":planned,
                          "configured_max_requests":args.max_requests,
                          "warning":"Check each free/non-billed account before opt-in."},indent=2))
        return
    rows=inspect(max_requests=args.max_requests)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row.__dict__,sort_keys=True)+"\n")
    warnings=[]
    if args.previous and args.previous.is_file():
        old=[Probe(**json.loads(l)) for l in args.previous.read_text().splitlines() if l.strip()]
        warnings=compare(old,rows)
    print(json.dumps({"saved":str(args.out),"scored_probes":len(rows),
                      "performance_warnings":warnings},indent=2))

if __name__=="__main__":main()
