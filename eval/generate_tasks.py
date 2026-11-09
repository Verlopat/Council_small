"""Deterministic Phase-A tasks with hidden edge cases and planted traps.

Original-generated, reproducible. Task gold values come from independent
arithmetic and algebra in this script, not from an LLM. Dev and heldout use
disjoint deterministic seeds. Hidden code tests remain out of the prompt.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def build(*,per_kind:int=30,seed:int=20261029,split:str="dev")->list[dict]:
    if not 1<=per_kind<=1000 or split not in {"dev","heldout"}:
        raise ValueError("Invalid task count or split")

    class PortableRNG:
        def __init__(self,initial:int):
            self.state=initial&0xffffffff
        def randint(self,low:int,high:int)->int:
            self.state=(1664525*self.state+1013904223)&0xffffffff
            return low+self.state%(high-low+1)
    rng=PortableRNG(seed+(0 if split=="dev" else 300000))
    rows=[]
    for i in range(per_kind):
        a=rng.randint(25,99)+(100 if split=="heldout" else 0)
        b=rng.randint(7,29)
        c=rng.randint(2,19)
        k=i%4
        if k==0:
            expression=f"({a} * {b} + {c} * {c}) % {b+13}"
            expected=(a*b+c*c)%(b+13)
            question=(f"A cooperative packs {a} crates with {b} units each, "
                      f"then receives {c} boxes of {c} additional units. "
                      f"How many units remain after making groups of exactly "
                      f"{b+13}? Report the leftover count as a final integer.")
        elif k==1:
            total=a*b+c
            expression=f"({total} + {b} - 1) // {b}"
            expected=(total+b-1)//b
            question=(f"A shipment has {a} parcels of {b} items each and "
                      f"{c} loose items. Each sealed carton holds at most {b} "
                      f"items. What is the minimum number of cartons, "
                      f"including the partially filled final carton? "
                      f"Give a final integer.")
        elif k==2:
            expression=f"({a} * {b} - {c}) // {b+3}"
            expected=(a*b-c)//(b+3)
            question=(f"A warehouse receives {a} pallets with {b} items per "
                      f"pallet. Exactly {c} are damaged and discarded. "
                      f"How many COMPLETE bundles of {b+3} items can it ship? "
                      f"Report only the final number of bundles.")
        else:
            expression=f"({a} * ({a} - 1) * ({a} - 2)) // 6 - {c}"
            expected=a*(a-1)*(a-2)//6-c
            question=(f"A committee chooses three people from {a} distinct "
                      f"volunteers, without regard to order. Exactly {c} "
                      f"triples are disallowed. How many allowed committees "
                      f"remain? Give a final integer.")
        rows.append({
            "id":f"{split[0].upper()}-N-{i:03d}","split":split,
            "kind":"numeric","prompt":question,"expected":str(expected),
            "checker_expression":expression,"license":"original-generated",
            "seed":seed,"difficulty":"multistep"})

        shift=rng.randint(2,13)
        sample=[-b,0,-c,2,3,a,-1]
        def reference(xs):
            return sum((x*x+shift if x>0 and x%2==0
                        else -abs(x) if x<0
                        else shift if x==0 else x+shift) for x in xs)
        cases=[[],[-1],[-2,0,2],[-1000000,1000000],
               [3,3,3],sample]
        rows.append({
            "id":f"{split[0].upper()}-C-{i:03d}","split":split,
            "kind":"code",
            "prompt":(f"Implement Python f(xs) for a list of integers. "
                      f"For positive even x, add x squared plus {shift}; "
                      f"for negative x, subtract its absolute value; "
                      f"for zero, add {shift}; for positive odd x, add "
                      f"x plus {shift}. Return the integer sum. "
                      f"Give the output for xs={sample} as a final integer "
                      f"after the code."),
            "expected":str(reference(sample)),
            "hidden_spec":{"language":"python","function":"f",
                           "cases":[{"input":xs,"expected":reference(xs)}
                                    for xs in cases]},
            "license":"original-generated","seed":seed,
            "difficulty":"edge_cases"})

        u=rng.randint(1,50)
        v=rng.randint(1,40)
        false=i%10 in {1,4,7}
        # A false identity often differs by ONE in the x-coefficient:
        # an off-by-one that is harder to catch by pattern alone.
        delta=1 if false else 0
        lhs=f"(x+{u})*(x+{v})"
        rhs=f"x**2+{u+v+delta}*x+{u*v}"
        rows.append({
            "id":f"{split[0].upper()}-S-{i:03d}","split":split,
            "kind":"symbolic",
            "prompt":(f"For all real x, is {lhs} equal to {rhs}? "
                      "Explain briefly, then finish with exactly "
                      "'Final answer: yes' or 'Final answer: no'."),
            "symbolic_identity":{"left":lhs,"right":rhs},
            "expected":"no" if false else "yes",
            "license":"original-generated","seed":seed,
            "difficulty":"identity_with_negative_cases"})
    return rows


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
