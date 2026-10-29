"""Entry point: python -m council.cli --mode research 'Research question'."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys
import uuid

from council.budget import RunBudget
from council.events import EventStore
from council.families import FAMILIES
from council.transport import FamilyTransport
from council.workflow import CouncilRunner, DEFAULT_SOLVERS, JUDGE, AUDITOR

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-aware multi-model research council")
    parser.add_argument("question", nargs="*", help="A research question")
    parser.add_argument("--mode", choices=("quick", "research", "full"), default="research")
    parser.add_argument("--deadline", type=float, default=300.0,
                        help="Total seconds, including synthesis and audit")
    parser.add_argument("--timeout", type=float, default=28.0,
                        help="Per inference request timeout")
    parser.add_argument("--requirements-file", type=Path,
                        help="JSON document with objective, constraints and questions")
    parser.add_argument("--run-dir", type=Path, default=Path("runs"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--recompute", metavar="RUN_ID",
                        help="Replay orchestration from recorded role responses without API calls")
    parser.add_argument("--resume", metavar="RUN_ID",
                        help="Resume missing role responses from checkpoint, may use free APIs")
    parser.add_argument("--replay", metavar="RUN_ID",
                        help="Print a prior run's final logged result without API calls")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show role plan without API calls")
    parser.add_argument("--list-families", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print complete JSON results")
    args = parser.parse_args(argv)
    if args.list_families:
        for name, family in FAMILIES.items():
            print(name + ": " + ", ".join(e.provider + "/" + e.model for e in family.endpoints))
        return 0
    if args.replay:
        db = args.run_dir / (args.replay + ".sqlite3")
        if not db.is_file():
            parser.error("Run not found")
        with EventStore(args.run_dir, args.replay) as events:
            completed = [e for e in events.replay() if e["event"] == "run_finished"]
        if not completed:
            parser.error("Run has no final result")
        print(json.dumps(completed[-1]["payload"]["result"], indent=2, ensure_ascii=False))
        return 0
    if args.recompute or args.resume:
        original_id = args.recompute or args.resume
        original_db = args.run_dir / (original_id + ".sqlite3")
        if not original_db.is_file():
            parser.error("Checkpoint not found")
        with EventStore(args.run_dir, original_id) as source:
            recorded = source.replay()
        metadata = next((e["payload"] for e in recorded
                         if e["event"] == "run_started"), None)
        if metadata is None:
            parser.error("Checkpoint has no start metadata")
        from council.replay import ReplayTransport, ResumeTransport
        mode = metadata.get("mode", "research")
        question = metadata.get("question", "")
        with EventStore(args.run_dir, original_id +
                        (".resumed" if args.resume else ".recomputed")) as destination:
            transport = ReplayTransport(recorded)
            if args.resume:
                transport = ResumeTransport(recorded,
                    FamilyTransport(timeout=args.timeout, record=destination.record))
            budget = RunBudget.start(args.deadline,
                 reserve=min(20.0, args.deadline / 3))
            if mode == "full":
                from council.full import FullCouncilRunner
                from council.requirements import Requirements
                reqdata=metadata.get("requirements",{})
                req=Requirements(reqdata.get("objective",question),
                     tuple(reqdata.get("constraints",[])),
                     tuple(reqdata.get("questions",[])))
                runner=FullCouncilRunner(transport,destination,budget,requirements=req)
            else:
                runner=CouncilRunner(transport,destination,budget)
            result=asyncio.run(runner.run(question,mode=mode))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    question = " ".join(args.question).strip()
    if not question:
        parser.error("Provide a research question, --list-families or --replay")
    if args.deadline <= 0 or args.timeout <= 1:
        parser.error("Deadline and timeout must be positive")
    if args.mode == "full":
        from council.full import FULL_SOLVERS
        solvers = FULL_SOLVERS
    else:
        solvers = DEFAULT_SOLVERS[:1] if args.mode == "quick" else DEFAULT_SOLVERS
    if args.dry_run:
        print(json.dumps({"mode": args.mode, "question": question,
                          "solvers": solvers, "judge": JUDGE,
                          "auditor": ("gemma" if args.mode == "full" else AUDITOR)
                            if args.mode != "quick" else None,
                          "deadline": args.deadline, "api_calls": 0}, indent=2))
        return 0
    run_id = args.run_id or uuid.uuid4().hex[:16]
    budget = RunBudget.start(args.deadline, reserve=min(20.0, args.deadline / 3))
    with EventStore(args.run_dir, run_id) as events:
        transport = FamilyTransport(timeout=args.timeout, record=events.record)
        if args.mode == "full":
            from council.full import FullCouncilRunner
            from council.requirements import Requirements
            req = (Requirements.from_file(args.requirements_file)
                   if args.requirements_file else Requirements(question))
            runner = FullCouncilRunner(transport, events, budget, requirements=req)
        else:
            runner = CouncilRunner(transport, events, budget)
        result = asyncio.run(runner.run(question, mode=args.mode))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        brief = result["research_result"]
        print("\nRun: " + run_id + " | status: " + brief["completion_status"])
        print("\nProposed approach:\n" + (brief["proposed_approach"] or "(none)"))
        print("\nHypotheses:\n" + "\n".join("- " + x for x in brief["hypotheses"]))
        print("\nUnresolved objections:\n" + "\n".join(
            "- " + x for x in brief["unresolved_objections"]))
        print("\nNext actions:\n" + "\n".join("- " + x for x in brief["next_actions"]))
        print("\nLimitations:\n" + "\n".join("- " + x for x in brief["limitations"]))
        print("\nStructured records saved locally to " + str(args.run_dir / (run_id + ".sqlite3")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
