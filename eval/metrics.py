"""Paired task-level confidence intervals."""
import random, statistics
from collections import defaultdict

def bootstrap_ci(deltas,n=10000,alpha=.05,seed=0):
    if not deltas or n<10 or not 0<alpha<1: raise ValueError("Invalid CI input")
    rng=random.Random(seed)
    means=sorted(statistics.fmean(rng.choices(deltas,k=len(deltas))) for _ in range(n))
    return statistics.fmean(deltas),means[int(n*alpha/2)],means[int(n*(1-alpha/2))-1]

def paired_deltas(rows,challenger="council",baseline="best_of_n",metric="correct"):
    values=defaultdict(lambda:defaultdict(list))
    for row in rows:
        if row.get("system") in {challenger,baseline}:
            values[row["task_id"]][row["system"]].append(float(row[metric]))
    return [statistics.fmean(x[challenger])-statistics.fmean(x[baseline])
            for task,x in sorted(values.items()) if x[challenger] and x[baseline]]

def earns_its_place(deltas,higher_is_better=True):
    mean,lo,hi=bootstrap_ci(deltas)
    return lo>0 if higher_is_better else hi<0

def summary(rows):
    if not rows:return {}
    keys=("false_verified","unresolved","no_op","composition_unchecked",
          "pressure_concession","calls","tokens","latency")
    return {k:statistics.fmean(float(row.get(k,0)) for row in rows) for k in keys}
