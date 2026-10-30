"""Validated YAML config; quotas are explicitly configured, never guessed."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from council.assignment import Assignment

@dataclass(frozen=True)
class CouncilConfig:
    mode:str
    deadline_seconds:float
    solvers:tuple[str,...]
    translator:str
    judge:str
    auditor:str
    max_claims:int
    hunter_cap:int
    per_call_timeout:float
    optional:dict
    rate_limits:dict
    caps:dict

    @property
    def assignment(self):
        return Assignment(self.solvers,self.translator,self.judge,self.auditor,
                          tuple(self.optional.get("critics",[])))

def load_config(path:Path)->CouncilConfig:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Install requirements.txt (PyYAML)") from exc
    data=yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data,dict):raise ValueError("Configuration must be a map")
    cfg=CouncilConfig(
        mode=str(data.get("mode","full")),
        deadline_seconds=float(data.get("deadline_seconds",600)),
        solvers=tuple(x["family"] if isinstance(x,dict) else x
                      for x in data.get("solvers",[])),
        translator=str(data.get("translator","glm")),
        judge=str(data.get("judge","gemini")),
        auditor=str(data.get("auditor","gemma")),
        max_claims=int(data.get("max_claims",12)),
        hunter_cap=int(data.get("hunter_cap",4)),
        per_call_timeout=float(data.get("per_call_timeout",28)),
        optional=dict(data.get("optional",{})),
        rate_limits=dict(data.get("rate_limits",{})),
        caps=dict(data.get("caps",{})))
    if cfg.mode not in {"quick","research","full"} or not 5<=cfg.deadline_seconds<=86400:
        raise ValueError("Bad mode or deadline")
    if not 1<=cfg.max_claims<=100 or not 0<=cfg.hunter_cap<=10 or not 2<=cfg.per_call_timeout<=120:
        raise ValueError("Bad caps or timeout")
    allowed_caps = {"messages", "verifier_calls", "repairs", "pair_exchanges"}
    if set(cfg.caps) - allowed_caps or any(
            type(value) is not int or not 1 <= value <= 20
            for value in cfg.caps.values()):
        raise ValueError("Invalid message-bus caps")
    _=cfg.assignment
    for provider,detail in cfg.rate_limits.items():
        if not isinstance(detail,dict) or any(
            not isinstance(x,(int,float)) or x<0 for x in detail.values()):
            raise ValueError("Rate limits must be explicitly numeric")
    return cfg
