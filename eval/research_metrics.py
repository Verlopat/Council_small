"""Research usefulness requires blinded expert annotations, not an LLM judge."""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import statistics

RUBRIC={
    "false_claims":"Unsupported or contradicted statements presented as facts",
    "missed_flaws":"Known missing assumptions or invalid steps not identified",
    "useful_corrections":"Valid, actionable changes justified by evidence",
    "preserved_disagreements":"Incompatible or unresolved approaches kept distinct",
    "proof_obligations":"Important security, reduction or feasibility obligations listed",
}

@dataclass(frozen=True)
class HumanAnnotation:
    task_id:str
    system:str
    blinded_rater_id:str
    criterion:str
    score:float
    notes:str=""

    def __post_init__(self):
        if (not self.task_id or not self.system or not self.blinded_rater_id or
            self.criterion not in RUBRIC or not 0<=self.score<=1):
            raise ValueError("Invalid independent human annotation")

def report(annotations:list[HumanAnnotation])->dict:
    by_key=defaultdict(list)
    distinct_raters=defaultdict(set)
    for a in annotations:
        key=(a.task_id,a.system,a.criterion)
        if a.blinded_rater_id in distinct_raters[key]:
            raise ValueError("Duplicate rater/criterion/task")
        distinct_raters[key].add(a.blinded_rater_id)
        by_key[key].append(a.score)
    per_task=[{"task_id":task,"system":system,"criterion":criterion,
               "mean_score":statistics.fmean(scores),
               "raters":len(scores),
               "range":max(scores)-min(scores)}
              for (task,system,criterion),scores in sorted(by_key.items())]
    groups=defaultdict(list)
    for row in per_task:
        groups[(row["system"],row["criterion"])].append(row["mean_score"])
    return {"per_task":per_task,
            "per_system":[{"system":system,"criterion":criterion,
                "mean_across_tasks":statistics.fmean(scores),
                "tasks":len(scores)}
                for (system,criterion),scores in sorted(groups.items())],
            "limitation":"Human ratings need blinded independent raters; no automated accuracy claim"}
