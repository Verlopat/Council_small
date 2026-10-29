"""Safe staged-evaluation work queue and call-budget plan.

This produces explicit jobs. It NEVER fires thousands of free API calls itself.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import json
from pathlib import Path
from eval.tasks import load

@dataclass(frozen=True)
class EvaluationJob:
    task_id:str
    kind:str
    run_index:int
    split:str
    council_calls_budget:int
    baseline_calls_budget:int

def plan(path:Path,*,split:str="dev",runs:int=3,call_budget:int=12):
    if runs<1 or runs>10 or call_budget<1 or call_budget>100:
        raise ValueError("Invalid experiment schedule")
    jobs=[]
    for item in load(path,split=split):
        for run in range(runs):
            jobs.append(EvaluationJob(item["id"],item["kind"],run,split,
                                      call_budget,call_budget))
    return jobs

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("tasks",type=Path)
    p.add_argument("--split",default="dev",choices=["dev","heldout"])
    p.add_argument("--runs",type=int,default=3)
    p.add_argument("--calls",type=int,default=12)
    args=p.parse_args(argv)
    print(json.dumps([asdict(job) for job in plan(
        args.tasks,split=args.split,runs=args.runs,call_budget=args.calls)],indent=2))
if __name__=="__main__":main()
