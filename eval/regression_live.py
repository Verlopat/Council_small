"""Explicitly opt-in, scored weekly provider regression, no paid fallthrough.

Model names are not proof of unchanged weights. Score the same 20 known tasks
against every configured endpoint, compare aggregate scores and inspect drift.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import time
import os
from council.families import FAMILIES
from council.transport import FamilyTransport
from council.quota import QuotaScheduler
from router_errors import CandidateError
from model_router import Candidate, Router
from eval.regression_probe import make,compare,Probe
from answer_validation import matches_expected

def fixed_tasks()->list[tuple[str,str,str]]:
    return [(f"probe-{i:02d}",f"Compute {i+11} * {i+19}. Answer only with the integer.",
             str((i+11)*(i+19))) for i in range(20)]

def candidates():
    seen=set()
    for family in FAMILIES.values():
        for endpoint in family.endpoints:
            key=(endpoint.provider,endpoint.model)
            if key not in seen:
                seen.add(key)
                yield family.name,endpoint

def inspect(*,max_requests:int,rate_limits:dict|None=None,failures:list|None=None):
    """Interleave endpoints fairly; stop at the exact opt-in request budget.

    With a cap smaller than 20 times the eligible endpoint count, regression
    coverage is INCOMPLETE and must never be called an all-model weekly test.
    """
    if not 1 <= max_requests <= 1000:
        raise ValueError("Unsafe request bound")
    router = Router(timeout=30)
    quota = QuotaScheduler(default_rate=30.0, default_burst=1)
    for provider,settings in (rate_limits or {}).items():
        quota.configure_provider(provider,
            rate_per_minute=float(settings["requests_per_minute"]),
            burst=int(settings.get("burst",1)),
            daily_requests=settings.get("daily_requests"),
            daily_tokens=settings.get("daily_tokens"),
            tokens_per_minute=settings.get("tokens_per_minute"))
    rows = []
    selected = []
    for family, endpoint in candidates():
        if not FamilyTransport._eligible(endpoint.provider):
            continue
        choice = Candidate(endpoint.provider, endpoint.model)
        try:
            eligible = router.expand(choice, set())
        except Exception:
            continue
        if eligible and eligible[0].model == endpoint.model:
            selected.append((family, endpoint, choice))
    attempts = 0
    for task_id, question, expected in fixed_tasks():
        # Round-robin across endpoints, not 20 calls to the first provider
        # before every other configured provider receives a single task.
        for family, endpoint, selected_model in selected:
            if attempts >= max_requests:
                return rows
            attempts += 1
            try:
                asyncio.run(quota.acquire(endpoint.provider, endpoint.model,
                    deadline=time.monotonic()+90,
                    expected_tokens=max(1,len(question)//3)+512))
                actual = router.generate(selected_model, question, max_output_tokens=512)
            except Exception as exc:
                kind=getattr(exc,"kind","quota_contention"
                             if isinstance(exc,TimeoutError) else "provider_error")
                quota.failure(endpoint.provider,endpoint.model,kind=kind,
                              retry_after=getattr(exc,"retry_after",None))
                if failures is not None:
                    failures.append({"provider":endpoint.provider,
                        "model":endpoint.model,"task":task_id,"kind":kind})
                # Provider errors are missing observations, not incorrect answers.
                continue
            quota.success(endpoint.provider,endpoint.model)
            rows.append(make(family, endpoint.model, task_id, actual,
                1.0 if matches_expected(actual, expected) else 0.0))
    return rows


def coverage(rows) -> dict:
    """Report per-endpoint task counts; do not mistake partial for complete."""
    counts = {}
    for row in rows:
        key = (row.family, row.model)
        counts[key] = counts.get(key, 0) + 1
    return {
        "sampled_endpoints": len(counts),
        "per_endpoint": [
            {"family": fam, "model": model, "completed": count,
             "required": 20, "complete": count == 20}
            for (fam, model), count in sorted(counts.items())
        ],
        "all_sampled_complete": bool(counts) and all(n == 20 for n in counts.values()),
        "limitation": "Unconfigured and ineligible endpoints are excluded, not silently marked passing",
    }

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--confirm-free",action="store_true")
    p.add_argument("--max-requests",type=int,default=20)
    p.add_argument("--out",type=Path,default=Path("runs")/"regression.jsonl")
    p.add_argument("--previous",type=Path)
    args=p.parse_args(argv)
    if not 1<=args.max_requests<=1000:p.error("Invalid request cap")
    planned=sum(20 for _ in candidates())
    if not args.confirm_free:
        print(json.dumps({"mode":"plan_only","requests_if_unlimited":planned,
                          "configured_max_requests":args.max_requests,
                          "warning":"Check each free/non-billed account before opt-in."},indent=2))
        return
    from council.config import load_config
    cfg=load_config(Path("council.yaml")) if Path("council.yaml").is_file() else None
    failures=[]
    rows=inspect(max_requests=args.max_requests,
                 rate_limits=cfg.rate_limits if cfg else None,
                 failures=failures)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row.__dict__,sort_keys=True)+"\n")
    warnings=[]
    if args.previous and args.previous.is_file():
        old=[Probe(**json.loads(l)) for l in args.previous.read_text().splitlines() if l.strip()]
        warnings=compare(old,rows)
    print(json.dumps({"saved":str(args.out),"scored_probes":len(rows),
                      "coverage":coverage(rows),
                      "provider_error_count":len(failures),
                      "provider_errors":failures[:100],
                      "performance_warnings":warnings},indent=2))

if __name__=="__main__":main()
