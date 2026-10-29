"""Deterministic original Phase-A tasks: 30 each of numeric, code and symbolic.

Generated questions are newly parameterized to reduce benchmark contamination.
Neither the prompt text nor task IDs are derived from a public test corpus.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random

def build(*,per_kind:int=30,seed:int=20261029,split:str="dev")->list[dict]:
    if not 1<=per_kind<=1000 or split not in {"dev","heldout"}:
        raise ValueError("Invalid task count or split")
    rng=random.Random(seed+(0 if split=="dev" else 300000))
    tasks=[]
    for i in range(per_kind):
        a,b=rng.randint(13,999),rng.randint(7,250)
        c=rng.randint(1,30)
        expression=f"({a} * {b}) - {c}"
        expected=a*b-c
        tasks.append({"id":f"{split[0].upper()}-N-{i:03d}",
                      "split":split,"kind":"numeric",
                      "prompt":f"Compute exactly {expression}. Give a final integer answer.",
                      "expected":str(expected),
                      "checker_expression":expression,
                      "license":"original-generated","seed":seed})
        k=rng.randint(2,20)
        n=rng.randint(3,30)
        tasks.append({"id":f"{split[0].upper()}-C-{i:03d}",
                      "split":split,"kind":"code",
                      "prompt":f"Write Python function f(xs) returning sum(x*x + {k} for x in xs). Demonstrate on list(range({n})).",
                      "expected":str(sum(x*x+k for x in range(n))),
                      "hidden_spec":{"language":"python",
                                     "behavior":"sum of x*x plus constant per list element",
                                     "constant":k,"test_input":list(range(n))},
                      "license":"original-generated","seed":seed})
        u,v=rng.randint(1,20),rng.randint(1,20)
        tasks.append({"id":f"{split[0].upper()}-S-{i:03d}",
                      "split":split,"kind":"symbolic",
                      "prompt":f"Is (x + {u})*(x + {v}) equal to x**2 + {u+v}*x + {u*v} for every real x? Show an algebraic proof.",
                      "symbolic_identity":{"left":f"(x+{u})*(x+{v})",
                                           "right":f"x**2+{u+v}*x+{u*v}"},
                      "license":"original-generated","seed":seed})
    return tasks

def save(path:Path,rows:list[dict])->None:
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n")

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--per-kind",type=int,default=30)
    parser.add_argument("--seed",type=int,default=20261029)
    parser.add_argument("--split",choices=["dev","heldout"],default="dev")
    args=parser.parse_args(argv)
    rows=build(per_kind=args.per_kind,seed=args.seed,split=args.split)
    save(args.out,rows)
    print(f"Saved {len(rows)} original {args.split} tasks to {args.out}")

if __name__=="__main__":
    main()
