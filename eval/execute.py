"""Bounded, opt-in live evaluation. Never claims improvement without scored tasks.

All API usage must be on accounts whose free/non-billed status you verified.
Use --plan before --confirm-free. No keys or answer texts are committed.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid
from council.budget import RunBudget
from council.events import EventStore
from council.full import FullCouncilRunner
from council.transport import FamilyTransport,FamilyUnavailable
from eval.tasks import load
from eval.baselines import majority,best_of_n,family_vote
from council.verify.arithmetic import check
from answer_validation import matches_expected

def requested_baseline_calls(council_calls: int, *, user_limit: int = 0,
                             safety_cap: int = 55) -> int:
    """Default: match Council's API-call count, subject to an explicit cap.

    user_limit=0 means try to match the full observed count. A truncated
    baseline must be flagged as unequal and excluded from paired comparisons.
    Matching calls is not the same as matching tokens, latency or tool access.
    """
    if council_calls < 0 or user_limit < 0 or safety_cap < 1:
        raise ValueError("Invalid baseline budget")
    return min(council_calls, user_limit or council_calls, safety_cap)


async def run_task(task,transport,events,*,deadline,baseline_samples=0):
    q=task["prompt"]
    budget=RunBudget.start(deadline,reserve=min(15.,deadline/4))
    initial=time.monotonic()
    runner=FullCouncilRunner(transport,events,budget)
    council=await runner.run(q)
    model_calls=sum(e["event"]=="model_call_started" for e in events.replay())
    result=council["research_result"]
    output={"task_id":task["id"],"system":"council",
            "answer":result.get("proposed_approach",""),
            "calls":model_calls,"equal_budget":True,"latency":time.monotonic()-initial,
            "unresolved":council.get("verdict",{}).get("status")!="answer",
            "composition_unchecked":council.get("composition",{}).get("outcome")=="unchecked"}
    if "expected" in task:
        output["correct"]=int(matches_expected(
            str(council.get("verdict",{}).get("answer") or ""),str(task["expected"])))
    else:
        output["correct"]=None
        output["manual_review_required"]=True
    baseline_outputs=[]
    baseline_budget=RunBudget.start(deadline,reserve=0)
    target_samples = requested_baseline_calls(
        model_calls, user_limit=baseline_samples)
    output["baseline_target_calls"] = target_samples
    output["comparison_basis"] = "equal API calls only; token and tool costs not yet matched"
    for sample_id in range(target_samples):
        if baseline_budget.remaining()<=5:break
        try:
            response=await transport.complete(
                "gpt-oss",q,baseline_budget,role="baseline",synthesis=True)
            baseline_outputs.append(response.text)
        except FamilyUnavailable:
            break
    if baseline_outputs:
        vote=majority(baseline_outputs)
        base={"task_id":task["id"],"system":"self_consistency",
              "answer":vote.answer,"calls":len(baseline_outputs),
              "equal_budget":len(baseline_outputs)==model_calls,
              "unresolved":vote.answer is None}
        if "expected" in task:
            base["correct"]=int(matches_expected(str(vote.answer or ""),
                                                 str(task["expected"])))
        else:base["correct"]=None
        output_base=[base]
        single={"task_id":task["id"],"system":"single",
                "answer":baseline_outputs[0],"calls":1,
                "equal_budget":model_calls==1,"unresolved":False}
        single["correct"]=(int(matches_expected(baseline_outputs[0],str(task["expected"])))
                           if "expected" in task else None)
        output_base.append(single)
        # Same arithmetic checker available to Council; gold answer is NOT used
        # for selection, only to score after choosing.
        independent=task.get("checker_expression")
        if independent:
            def tool_selector(answer):
                try:
                    proposed=int(answer.strip())
                    ok=check(independent,proposed).outcome=="pass"
                    return ok,float(ok)
                except ValueError:
                    return False,0.0
            selected=best_of_n(baseline_outputs,tool_selector)
            best={"task_id":task["id"],"system":"best_of_n",
                  "answer":selected.answer,"calls":len(baseline_outputs),
                  "equal_budget":len(baseline_outputs)==model_calls,
                  "unresolved":selected.answer is None}
            if "expected" in task:
                best["correct"]=int(matches_expected(str(selected.answer or ""),
                                                    str(task["expected"])))
            else:best["correct"]=None
            output_base.append(best)
    else:output_base=[]
    # Plain cross-family voting is a distinct control from repeated gpt-oss.
    # Six families are required; a provider endpoint never gets an extra vote.
    family_outputs={}
    families=("gpt-oss","command","gemma","nemotron","gemini","glm")
    family_budget=RunBudget.start(deadline,reserve=0)
    for family in families:
        if family_budget.remaining()<=5:break
        try:
            answer=await transport.complete(family,q,family_budget,
                                             role="baseline_vote6",synthesis=True)
            family_outputs[family]=answer.text
        except FamilyUnavailable:
            continue
    vote6=family_vote(family_outputs)
    vote_row={"task_id":task["id"],"system":"vote6",
              "answer":vote6.answer,"calls":vote6.calls,
              "equal_budget":vote6.calls==model_calls,
              "independent_families":len(family_outputs),
              "unresolved":vote6.answer is None}
    vote_row["correct"]=(int(matches_expected(str(vote6.answer or ""),
                            str(task["expected"]))) if "expected" in task else None)
    return [output]+output_base+[vote_row]

async def execute(tasks,*,out_dir:Path,deadline:float,max_tasks:int,
                  baseline_samples:int):
    out_dir.mkdir(parents=True,exist_ok=True)
    rows=[]
    for task in tasks[:max_tasks]:
        run_id=uuid.uuid4().hex[:16]
        with EventStore(out_dir,run_id) as events:
            transport=FamilyTransport(record=events.record)
            rows+=await run_task(task,transport,events,deadline=deadline,
                                 baseline_samples=baseline_samples)
    dest=out_dir/"results.jsonl"
    with dest.open("w",encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row,ensure_ascii=False)+"\n")
    return dest,rows

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks",type=Path)
    parser.add_argument("--split",choices=("dev","heldout"),default="dev")
    parser.add_argument("--max-tasks",type=int,default=3)
    parser.add_argument("--deadline",type=float,default=240)
    parser.add_argument("--baseline-samples",type=int,default=0,
                        help="0 (default) aims to match Council calls, capped at 55; explicit positive value is a smaller hard cap")
    parser.add_argument("--out-dir",type=Path,default=Path("runs")/"eval")
    parser.add_argument("--confirm-free",action="store_true")
    args=parser.parse_args(argv)
    if not 1<=args.max_tasks<=100 or not 0<=args.baseline_samples<=55:
        parser.error("Unsafe task or sample count")
    tasks=load(args.tasks,split=args.split)
    upper_calls=args.max_tasks*(55+(args.baseline_samples or 55)+6)
    if not args.confirm_free:
        print(json.dumps({"mode":"plan_only","tasks":min(len(tasks),args.max_tasks),
                          "per_task_deadline":args.deadline,
                          "max_possible_calls_warning":upper_calls,
                          "warning":"No APIs called. Confirm free/non-billed account limits. Equal CALLS are not equal TOKENS or tool availability."},indent=2))
        return
    path,rows=asyncio.run(execute(tasks,out_dir=args.out_dir,
                       deadline=args.deadline,max_tasks=args.max_tasks,
                       baseline_samples=args.baseline_samples))
    print(json.dumps({"saved":str(path),"rows":len(rows),
                      "warning":"Open-ended research rows need blinded human scoring"},indent=2))

if __name__=="__main__":
    main()
