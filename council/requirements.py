"""Research requirements are explicit; never silently reinterpret user constraints."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass(frozen=True)
class Requirements:
    objective: str
    constraints: tuple[str,...] = ()
    questions: tuple[str,...] = ()

    @classmethod
    def from_file(cls,path:Path):
        data=json.loads(Path(path).read_text(encoding="utf-8"))
        objective=data.get("objective","")
        if not isinstance(objective,str) or not objective.strip():
            raise ValueError("Missing objective")
        for key in ("constraints","questions"):
            if not isinstance(data.get(key,[]),list) or any(
                    not isinstance(x,str) or not x.strip() for x in data.get(key,[])):
                raise ValueError("Invalid requirement list")
        return cls(objective,tuple(data.get("constraints",[])),
                   tuple(data.get("questions",[])))

    def as_data(self):
        return {"objective":self.objective,
                "constraints":list(self.constraints),
                "questions":list(self.questions)}
