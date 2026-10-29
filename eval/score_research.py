"""Aggregate blinded manual research annotations. No automatic correctness judge."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from eval.research_metrics import HumanAnnotation,report

def score(path:Path)->dict:
    rows=[HumanAnnotation(**json.loads(line)) for line in
          Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return report(rows)

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("annotations",type=Path)
    args=parser.parse_args(argv)
    print(json.dumps(score(args.annotations),indent=2,ensure_ascii=False))
if __name__=="__main__":
    main()
