"""Only repeated *scored* probes indicate quality changes, not output hashes alone."""
from dataclasses import dataclass
import hashlib

@dataclass(frozen=True)
class Probe:
    family:str
    model:str
    task_id:str
    score:float
    output_hash:str

def make(family,model,task_id,text,score):
    return Probe(family,model,task_id,float(score),hashlib.sha256(text.encode()).hexdigest())

def compare(previous,latest,threshold=.15):
    prev={(p.family,p.model,p.task_id):p for p in previous}
    warnings=[]
    for item in latest:
        old=prev.get((item.family,item.model,item.task_id))
        if old is not None and old.score-item.score>=threshold:
            warnings.append({"model":item.model,"task":item.task_id,
                "score_drop":old.score-item.score,
                "output_changed":old.output_hash!=item.output_hash})
    return warnings
