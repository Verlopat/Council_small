"""Compare scored Council evaluations with paired task-level bootstrap CIs.

Do not mistake candidate-oracle accuracy for the accuracy of a selected
answer. Compare only samples with equal observed API-call budgets when
comparing Council to a baseline. No live API calls here.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from eval.metrics import paired_deltas,bootstrap_ci,summary


def _read(path):
    path=Path(path)
    source=path/"results.jsonl" if path.is_dir() else path
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def analyze(file,baseline="self_consistency",metric="correct"):
    rows=_read(file)
    usable=[r for r in rows if r.get(metric) is not None]
    differences=paired_deltas(usable,baseline=baseline,metric=metric)
    council=[x for x in rows if x.get("system")=="council"]
    verified=[x for x in council if x.get("verified")==1 and
              x.get("false_verified") is not None]
    def avg(key):
        values=[float(x[key]) for x in council if x.get(key) is not None]
        return (sum(values)/len(values) if values else None)
    return {"observations":len(rows),"paired_tasks":len(differences),
            "task_bootstrap_ci":bootstrap_ci(differences) if differences else None,
            "council_metrics":summary(council),
            "selected_accuracy":avg("correct"),
            "verified_accuracy_over_all_tasks":avg("correct_verified"),
            "candidate_oracle_upper_bound":avg("correct_candidate"),
            "verified_count":len(verified),
            "false_verified_rate_among_verified":(
                sum(int(x["false_verified"]) for x in verified)/len(verified)
                if verified else None),
            "note":"Candidate-oracle accuracy uses hindsight across proposals "
                   "and is NOT a deployable baseline or independent proof."}


def paired_mode_comparison(quick_path, full_path, metric="correct"):
    """Compare paired tasks, averaging repeats before resampling task IDs.

    Do not silently keep only the last repeat of a task. Repeats are
    correlated observations; confidence intervals must resample distinct
    tasks rather than treating all repeated runs as independent.
    """
    from collections import defaultdict
    def collect(path):
        groups=defaultdict(list)
        for row in _read(path):
            if (row.get("system")=="council"
                    and row.get(metric) is not None):
                groups[row["task_id"]].append(row)
        return groups
    quick,full=collect(quick_path),collect(full_path)
    paired={}
    for task_id in sorted(set(quick)&set(full)):
        q,f=quick[task_id],full[task_id]
        kinds={r.get("kind") or "unknown" for r in q+f}
        if len(kinds)!=1:
            raise ValueError("Task kind differs across paired runs: "+task_id)
        paired[task_id]=(
            next(iter(kinds)),
            sum(float(row[metric]) for row in q)/len(q),
            sum(float(row[metric]) for row in f)/len(f),
            min(len(q),len(f)))
    def calculate(items):
        deltas=[f-q for kind,q,f,reps in items]
        n=len(deltas)
        return {"paired_tasks":n,
                "paired_replicate_attempts":sum(reps for _,_,_,reps in items),
                "full_minus_quick_ci":bootstrap_ci(deltas) if deltas else None,
                "quick_accuracy":sum(q for _,q,_,_ in items)/n if n else None,
                "full_accuracy":sum(f for _,_,f,_ in items)/n if n else None}
    return {
        "overall":calculate(list(paired.values())),
        "by_kind":{
            kind:calculate([row for row in paired.values() if row[0]==kind])
            for kind in sorted({row[0] for row in paired.values()})},
        "note":"Repeated attempts are averaged per distinct task before "
               "task-level bootstrapping; missing or ungraded outcomes excluded."}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results",type=Path,
                        help="One results.jsonl or evaluation directory")
    parser.add_argument("second",type=Path,nargs="?",
                        help="Optional second evaluation directory (quick then full)")
    parser.add_argument("--baseline",default="self_consistency",
                        help="Fair equal-call baseline; best_of_n may be oracle-assisted and excluded")
    parser.add_argument("--metric",default="correct")
    args=parser.parse_args(argv)
    if args.second is not None:
        result={"quick":analyze(args.results,args.baseline,args.metric),
                "full":analyze(args.second,args.baseline,args.metric),
                "full_vs_quick":paired_mode_comparison(
                    args.results,args.second,args.metric)}
    else:
        result=analyze(args.results,args.baseline,args.metric)
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
