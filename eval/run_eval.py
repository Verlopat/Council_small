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
    quick={r["task_id"]:r for r in _read(quick_path)
           if r.get("system")=="council" and r.get(metric) is not None}
    full={r["task_id"]:r for r in _read(full_path)
          if r.get("system")=="council" and r.get(metric) is not None}
    pairs={tid:(quick[tid],full[tid]) for tid in sorted(set(quick)&set(full))}
    def calculate(items):
        deltas=[float(f[metric])-float(q[metric]) for q,f in items]
        return {"paired_tasks":len(deltas),
                "full_minus_quick_ci":bootstrap_ci(deltas) if deltas else None,
                "quick_accuracy":sum(float(q[metric]) for q,f in items)/len(items)
                                 if items else None,
                "full_accuracy":sum(float(f[metric]) for q,f in items)/len(items)
                                if items else None}
    result={"overall":calculate(list(pairs.values())),"by_kind":{}}
    kinds=sorted(set(q.get("kind") or "unknown" for q,f in pairs.values()))
    for kind in kinds:
        items=[pair for pair in pairs.values()
               if (pair[0].get("kind") or "unknown")==kind]
        result["by_kind"][kind]=calculate(items)
    return result


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
