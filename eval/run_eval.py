"""Analyze precomputed JSONL comparisons with task-bootstrap confidence intervals."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from eval.metrics import paired_deltas,bootstrap_ci,summary

def analyze(file,baseline="best_of_n",metric="correct"):
    rows=[json.loads(line) for line in Path(file).read_text().splitlines() if line.strip()]
    differences=paired_deltas(rows,baseline=baseline,metric=metric)
    return {"observations":len(rows),"paired_tasks":len(differences),
            "task_bootstrap_ci":bootstrap_ci(differences) if differences else None,
            "council_metrics":summary([x for x in rows if x.get("system")=="council"])}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("results",type=Path)
    parser.add_argument("--baseline",default="best_of_n")
    args=parser.parse_args(argv)
    print(json.dumps(analyze(args.results,args.baseline),indent=2))

if __name__=="__main__":
    main()
