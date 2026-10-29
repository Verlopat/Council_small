"""Single call, six-family vote, majority self-consistency and tool-selected best-of-N."""
from collections import Counter
from dataclasses import dataclass

@dataclass(frozen=True)
class Baseline:
    name: str
    answer: str | None
    candidates: tuple[str,...]
    calls: int
    reason: str

def majority(outputs,name="self_consistency"):
    if not outputs:return Baseline(name,None,(),0,"no samples")
    ranked=Counter(x.strip() for x in outputs)
    value,count=ranked.most_common(1)[0]
    accepted=value if 2*count>len(outputs) else None
    return Baseline(name,accepted,tuple(outputs),len(outputs),
                    "majority is not proof" if accepted else "no majority")

def best_of_n(outputs,verifier):
    eligible=[]
    for index,answer in enumerate(outputs):
        valid,score=verifier(answer)
        if valid: eligible.append((float(score),-index,answer))
    selected=max(eligible)[-1] if eligible else None
    return Baseline("best_of_n",selected,tuple(outputs),len(outputs),
                    "tool-selected within verifier scope" if selected else "no valid answer")

async def sample(call,prompt,n,*,mode,verifier=None):
    if not 1<=n<=100:raise ValueError("Invalid sample count")
    outputs=[await call(prompt,i) for i in range(n)]
    if mode=="single":return Baseline("single",outputs[0],tuple(outputs),n,"one call")
    if mode in {"self_consistency","vote6"}:return majority(outputs,mode)
    if mode=="best_of_n" and verifier:return best_of_n(outputs,verifier)
    raise ValueError("Unknown baseline or missing verifier")
