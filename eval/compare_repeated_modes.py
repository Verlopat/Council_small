"""Compare two or more quick/full Phase-A replicates without pseudo-replication.

A repeat of the same task is NOT a new independent task. Bootstrap sampling
uses distinct task IDs and averages their paired replicate differences.
No API calls, credentials, or sandbox execution are needed for reporting.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path
from eval.metrics import bootstrap_ci


def _load(root:Path,mode:str,repeat:int)->dict:
    path=root/f"{mode}_{repeat}"/"results.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}; rerun incomplete benchmark")
    rows={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row=json.loads(line)
        if row.get("system")!="council":
            continue
        task_id=row.get("task_id")
        if not isinstance(task_id,str) or not task_id or task_id in rows:
            raise ValueError(f"Invalid/duplicate task ID in {path}")
        if row.get("mode") not in (None,mode):
            raise ValueError(f"Wrong Council mode in {path}: {task_id}")
        correct=row.get("correct")
        if correct not in (0,1,None) or type(correct) is bool:
            raise ValueError(f"Invalid correctness score in {path}: {task_id}")
        rows[task_id]=row
    if not rows:
        raise ValueError(f"No Council rows in {path}")
    return rows


def summarize(root:Path,*,count:int=2)->dict:
    if not 1<=count<=20:
        raise ValueError("Replicate count must be between 1 and 20")
    datasets={}
    for mode in ("quick","full"):
        datasets[mode]=[_load(Path(root),mode,i) for i in range(1,count+1)]
    paired=defaultdict(list)
    observed=defaultdict(list)
    missing=0
    for repeat in range(count):
        quick,full=datasets["quick"][repeat],datasets["full"][repeat]
        if set(quick)!=set(full):
            raise ValueError(f"Quick/full task sets differ in repeat {repeat+1}")
        for task_id in sorted(quick):
            q,f=quick[task_id],full[task_id]
            if q.get("kind")!=f.get("kind"):
                raise ValueError(f"Quick/full task kinds differ: {task_id}")
            kind=q.get("kind") or "unknown"
            for mode,row in (("quick",q),("full",f)):
                observed[mode].append({
                    "task":task_id,"kind":kind,"correct":row.get("correct"),
                    "calls":row.get("calls"),"latency":row.get("latency")})
            if q["correct"] is None or f["correct"] is None:
                missing+=1
            else:
                paired[task_id].append((kind,q["correct"],f["correct"]))
    def describe(task_ids):
        scores=[(tid,paired[tid]) for tid in task_ids if paired[tid]]
        # Each distinct task contributes ONE paired mean, regardless of
        # how many replicates it happened to complete.
        differences=[
            sum(f-q for _,q,f in samples)/len(samples)
            for _,samples in scores]
        qs=[sum(q for _,q,_ in samples)/len(samples)
            for _,samples in scores]
        fs=[sum(f for _,_,f in samples)/len(samples)
            for _,samples in scores]
        n=len(scores)
        return {
            "distinct_scored_tasks":n,
            "scored_replicate_pairs":sum(len(samples) for _,samples in scores),
            "quick_mean":sum(qs)/n if n else None,
            "full_mean":sum(fs)/n if n else None,
            "full_minus_quick_mean":sum(differences)/n if n else None,
            "task_bootstrap_95pct_ci":(
                bootstrap_ci(differences) if differences else None)}
    unique=sorted(paired)
    kinds=sorted({samples[0][0] for samples in paired.values() if samples})
    def mode_summary(mode):
        rows=observed[mode]
        grades=[r["correct"] for r in rows if r["correct"] is not None]
        calls=[r["calls"] for r in rows
               if type(r["calls"]) in (int,float) and r["calls"]>=0]
        latencies=[r["latency"] for r in rows
                   if type(r["latency"]) in (int,float) and r["latency"]>=0]
        return {"runs":count,"total_task_attempts":len(rows),
                "graded_attempts":len(grades),
                "ungraded_attempts":len(rows)-len(grades),
                "mean_accuracy_per_attempt":sum(grades)/len(grades) if grades else None,
                "total_reported_call_starts":sum(calls),
                "mean_reported_call_starts_per_task":(
                    sum(calls)/len(calls) if calls else None),
                "mean_seconds_per_task":(
                    sum(latencies)/len(latencies) if latencies else None)}
    return {"quick":mode_summary("quick"),"full":mode_summary("full"),
            "paired":{"overall":describe(unique),
                      "by_kind":{kind:describe(
                          [tid for tid in unique if paired[tid]
                           and paired[tid][0][0]==kind]) for kind in kinds},
                      "ungraded_pairs":missing},
            "limitations":[
                "Repeated runs on the same task are correlated; bootstrap resamples task IDs, not replicate rows.",
                "Reported calls are started requests, not provider token/billing usage.",
                "Any code task with unavailable sandbox has ungraded correctness.",
                "Two replicates alone cannot establish statistical superiority.",
                "Model comparisons do not independently prove security-game definitions."]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--count",type=int,default=2)
    args=parser.parse_args(argv)
    try:
        result=summarize(args.root,count=args.count)
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
