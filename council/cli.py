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

def print_compact_result(result: dict, run_id: str, run_dir: Path) -> None:
    """Readable default report; complete diagnostics remain in --verbose/--json."""
    brief=result.get("research_result") or {}
    print("\nRun: "+run_id+" | status: "+str(brief.get("completion_status","unknown")))
    topics=result.get("topic_consolidation") or []
    verified=result.get("final_answer")
    candidates=result.get("candidate_answers") or {}
    if verified is not None:
        print("Evidence-supported scoped final answer: "+str(verified))
    elif (result.get("answer_selection") or {}).get("answer") is not None:
        selection=result["answer_selection"]
        label=("Executed agreement (not a formal proof)" if
               selection.get("basis")=="executed_agreement_not_formal_proof" else
               "Self-consistent execution (unverified)")
        print(label+": "+str(selection["answer"]))
    elif candidates:
        visible=[str(x)+": "+str(v) for x,v in candidates.items() if v is not None]
        if visible:
            print("Unverified candidate answer(s): "+" | ".join(visible[:3]))
    if topics:
        print("\nBest answer per game (RFC alignment; advisory, not verified):")
        for row in topics:
            title=str(row.get("topic","")).replace("_"," ").title()
            summary=str(row.get("summary") or row.get("best_statement") or "")
            selected=row.get("best_version_id")
            if selected:
                print("- "+title+" [§"+str(row.get("section") or "?")+"] "+
                      "["+str(selected)+"]: "+summary[:550])
            else:
                print("- "+title+": No fully selected source-aligned version. "+
                      (summary[:240] if row.get("reference_complete")
                       else "Source comparison unavailable."))
            missing=row.get("missing") or []
            if missing:
                print("  Missing: "+"; ".join(str(x) for x in missing[:2])[:260])
    disagreement=result.get("disagreement_report") or {}
    if disagreement.get("views") and not topics:
        print("\nCompeting research views (unverified disagreements):")
        for view in disagreement["views"][:4]:
            first=(view.get("claims") or [{}])[0]
            print("- "+str(view.get("proposal_id"))+" / "+
                  str(view.get("family"))+": "+
                  str(first.get("statement",""))[:250])
            for objection in (view.get("objections") or [])[:2]:
                print("    disputed: "+str(objection.get("issue",""))[:170])
    if brief.get("judge_summary"):
        print("\nJudge summary (advisory, not independent proof):\n"+
              str(brief["judge_summary"])[:1800])
    elif not topics:
        print("\nProposed approach (unverified):\n"+
              str(brief.get("proposed_approach") or "(no proposal)")[:1400])
    sections=result.get("open_objections")
    if isinstance(sections,list):
        print("\nOpen objections (source-quoted valid, advisory):")
        for row in sections[:6]:
            print("- "+str(row.get("id",""))+": "+
                  str(row.get("issue",""))[:350])
        if not sections:
            print("(none grounded; unjudged issues remain in the audit records)")
        if len(sections)>6:
            print("... "+str(len(sections)-6)+" more in structured records")
    else:
        remaining=brief.get("unresolved_objections") or []
        if remaining:
            print("\nUnresolved objections (not independently verified):")
            for issue in remaining[:4]:
                print("- "+str(issue)[:350])
    # Local patterns are noisy; print them by default ONLY for the selected
    # version or a version that the topic judge explicitly contradicted.
    selected={row.get("best_version_id") for row in topics
              if row.get("best_version_id")}
    contradicted={v.get("id") for row in topics
                  for v in row.get("versions",[]) or []
                  if v.get("status")=="contradicts"}
    watch=selected|contradicted
    all_findings=((result.get("advisory_findings") or [])+
                  (result.get("audit_advisory_findings") or []))
    messages=[]
    for entry in all_findings:
        if entry.get("claim_id") in watch:
            notice=(str(entry.get("claim_id"))+": "+
                    str(entry.get("message") or ""))
            if notice not in messages:
                messages.append(notice)
    if messages:
        print("\nSelected/contradicted-claim warnings (heuristic):")
        for notice in messages[:4]:
            print("- "+notice[:300])
        if len(messages)>4:
            print("... "+str(len(messages)-4)+" more with --verbose")
    coverage=result.get("role_coverage") or {}
    if coverage:
        actual=coverage.get("valid_proposer_families") or []
        expected=coverage.get("requested_solvers") or []
        print("\nCoverage: "+str(len(actual))+"/"+str(len(expected))+
              " valid solvers; independent audit "+
              ("completed" if coverage.get("independent_audit_completed")
               else "unavailable"))
    verdict=result.get("verdict") or {}
    if verdict:
        cause=verdict.get("cause")
        if cause=="definition_reference_only":
            cause="game-text comparison cannot certify cryptographic correctness"
        print("Evidence verdict: "+str(verdict.get("status","unresolved"))+
              (" ("+str(cause)+")" if cause else ""))
    warnings=result.get("warnings") or []
    provider_failures=[]
    for item in warnings:
        message=str(item)
        if (message.startswith(
                ("proposal/","judge/","topic_judge/","audit/",
                 "objection_judge/","translate/","repair/"))
                and any(keyword in message.casefold()
                        for keyword in ("unavailable","rate_limit","timeout"))):
            provider_failures.append(message)
    if provider_failures:
        print("Provider failures: "+" | ".join(provider_failures[:2])[:380])
    pending=result.get("unjudged_objections") or []
    if pending:
        print("Unjudged objections retained in records: "+str(len(pending)))
    print("Run records: "+str(run_dir/(run_id+".sqlite3"))+
          " (use --verbose or --json for details)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-aware multi-model research council")
    parser.add_argument("question", nargs="*", help="A research question")
    parser.add_argument("--mode", choices=("quick", "research", "full"), default=None)
    parser.add_argument("--deadline", type=float, default=None,
                        help="Total seconds, including synthesis and audit")
    parser.add_argument("--timeout", type=float, default=None,
                        help="Per inference request timeout")
    parser.add_argument("--config", type=Path, default=Path("council.yaml"))
    parser.add_argument("--paper-index", type=Path,
                        help="Existing SQLite paper index for scoped, non-certifying quote retrieval")
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
    parser.add_argument("--provider-report", action="store_true",
                        help="Show all configured provider lineages and local free-key eligibility without API calls")
    parser.add_argument("--json", action="store_true", help="Print complete JSON results")
    parser.add_argument("--verbose", action="store_true",
                        help="Print full reviewer, claim, source and obligation diagnostics")
    args = parser.parse_args(argv)
    cfg = None
    if (not (args.list_families or args.replay or args.recompute or args.resume)
            and args.config.is_file()):
        from council.config import load_config
        cfg = load_config(args.config)
    args.mode = args.mode or (cfg.mode if cfg else "research")
    if ((args.deadline is not None and args.deadline <= 0) or
            (args.timeout is not None and args.timeout <= 1)):
        parser.error("Deadline and timeout must be positive")
    if args.paper_index is not None and not args.paper_index.is_file():
        parser.error("--paper-index must identify an existing SQLite corpus")
    if args.list_families:
        for name, family in FAMILIES.items():
            print(name + ": " + ", ".join(e.provider + "/" + e.model for e in family.endpoints))
        return 0
    if args.provider_report:
        from council.providers import provider_coverage
        from council.config import load_config
        if args.mode == "full":
            selection = load_config(args.config) if args.config.is_file() else None
            active = (set(selection.solvers) |
                      {selection.translator, selection.judge, selection.auditor}
                      if selection else
                      {"gpt-oss", "command", "nemotron", "glm", "gemini", "gemma"})
            active.discard(None)
            active.update(selection.optional.get("critics", []) if selection else [])
        elif args.mode == "quick":
            selection = load_config(args.config) if args.config.is_file() else None
            active = ({selection.solvers[0], selection.translator, selection.judge}
                      if selection and selection.solvers
                      else {"gpt-oss", "glm", "gemini"})
        else:
            active = set(DEFAULT_SOLVERS) | {JUDGE, AUDITOR}
        print(json.dumps(provider_coverage(active_families=active), indent=2))
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
        from council.verify.source import PaperIndex
        mode = metadata.get("mode", "research")
        question = metadata.get("question", "")
        with EventStore(args.run_dir, original_id +
                        (".resumed" if args.resume else ".recomputed")) as destination:
            transport = ReplayTransport(recorded)
            if args.resume:
                transport = ResumeTransport(recorded,
                    FamilyTransport(timeout=args.timeout or 28.0,
                                    strict_timeout=args.timeout is not None,
                                    record=destination.record))
            replay_deadline=args.deadline if args.deadline is not None else 300.0
            budget = RunBudget.start(replay_deadline,
                 reserve=min(20.0, replay_deadline / 3))
            if mode == "quick" and metadata.get("pipeline") == "evidence":
                from council.full import QuickCouncilRunner
                from council.requirements import Requirements
                reqdata=metadata.get("requirements",{})
                req=Requirements(reqdata.get("objective",question),
                    tuple(reqdata.get("constraints",[])),
                    tuple(reqdata.get("questions",[])))
                allocation=metadata.get("role_assignment", {})
                first=tuple(allocation.get("solvers",("gpt-oss",)))
                runner=QuickCouncilRunner(
                    transport,destination,budget,requirements=req,
                    solver=first[0] if first else "gpt-oss",
                    translator_family=allocation.get("translator","glm"),
                    judge_family=allocation.get("judge","gemini"),
                    solver_strategies=metadata.get("solver_strategies", {}),
                    paper_index=(PaperIndex(args.paper_index)
                                 if args.paper_index else None))
            elif mode == "full":
                from council.full import FullCouncilRunner
                from council.requirements import Requirements
                reqdata=metadata.get("requirements",{})
                req=Requirements(reqdata.get("objective",question),
                     tuple(reqdata.get("constraints",[])),
                     tuple(reqdata.get("questions",[])))
                allocation=metadata.get("role_assignment",{})
                runner=FullCouncilRunner(transport,destination,budget,requirements=req,
                    solvers=tuple(allocation.get("solvers",("gpt-oss","command","nemotron"))),
                    translator_family=allocation.get("translator","glm"),
                    judge_family=allocation.get("judge","gemini"),
                    auditor_family=allocation.get("auditor","gemma"),
                    caps=metadata.get("debate_caps",{}),
                    solver_strategies=metadata.get("solver_strategies",{}),
                    paper_index=(PaperIndex(args.paper_index)
                                 if args.paper_index else None))
            else:
                runner=CouncilRunner(transport,destination,budget)
            result=asyncio.run(runner.run(question,mode=mode))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    question = " ".join(args.question).strip()
    if not question:
        parser.error("Provide a research question, --list-families or --replay")
    if args.mode in ("quick", "full"):
        from council.full import FULL_SOLVERS
        configured = cfg.solvers if cfg else FULL_SOLVERS
        if args.mode == "quick" and not configured:
            parser.error("Quick mode requires at least one solver family")
        solvers = configured[:1] if args.mode == "quick" else configured
    else:
        solvers = cfg.solvers if cfg else DEFAULT_SOLVERS
    if args.deadline is None:
        args.deadline=(cfg.deadline_seconds if cfg is not None else 300.0)
    if args.dry_run:
        print(json.dumps({"mode": args.mode, "question": question,
                          "solvers": solvers,
                          "strategies": cfg.solver_strategies if cfg else None,
                          "translator": cfg.translator if cfg else "glm",
                          "judge": cfg.judge if cfg else JUDGE,
                          "auditor": (cfg.auditor if cfg else "gemma")
                            if args.mode == "full" else
                            (AUDITOR if args.mode == "research" else None),
                          "deadline": args.deadline, "api_calls": 0}, indent=2))
        return 0
    paper_index=None
    if args.paper_index:
        from council.verify.source import PaperIndex
        paper_index=PaperIndex(args.paper_index)
    run_id = args.run_id or uuid.uuid4().hex[:16]
    budget = RunBudget.start(args.deadline, reserve=min(20.0, args.deadline / 3))
    with EventStore(args.run_dir, run_id) as events:
        transport = FamilyTransport(timeout=(
            args.timeout if args.timeout is not None else
            cfg.per_call_timeout if cfg else 28.0),
            strict_timeout=args.timeout is not None,
            record=events.record)
        if cfg:
            for provider, settings in cfg.rate_limits.items():
                transport.quota.configure_provider(provider,
                    rate_per_minute=float(settings["requests_per_minute"]),
                    burst=int(settings.get("burst",1)),
                    daily_requests=settings.get("daily_requests"),
                    daily_tokens=settings.get("daily_tokens"),
                    tokens_per_minute=settings.get("tokens_per_minute"))
        if args.mode == "full":
            from council.full import FullCouncilRunner
            from council.requirements import Requirements
            req = (Requirements.from_file(args.requirements_file)
                   if args.requirements_file else Requirements(question))
            runner = FullCouncilRunner(transport, events, budget, requirements=req,
                solvers=cfg.solvers if cfg else FULL_SOLVERS,
                max_claims=cfg.max_claims if cfg else 12,
                hunter_cap=cfg.hunter_cap if cfg else 4,
                translator_family=cfg.translator if cfg else "glm",
                judge_family=cfg.judge if cfg else "gemini",
                auditor_family=cfg.auditor if cfg else "gemma",
                enable_coverage=(cfg.optional.get("coverage_llm",True) if cfg else True),
                enable_relevance=(cfg.optional.get("relevance_check",False) if cfg else False),
                critics=(tuple(cfg.optional.get("critics",[])) if cfg else ()),
                adaptive_seeds=(cfg.optional.get("adaptive_seeds",False) if cfg else False),
                enable_repairs=(cfg.optional.get("repair_round",True) if cfg else True),
                caps=(cfg.caps if cfg else {}), paper_index=paper_index,
                solver_strategies=(cfg.solver_strategies if cfg else None))
        elif args.mode == "quick":
            from council.full import QuickCouncilRunner
            from council.requirements import Requirements
            req=(Requirements.from_file(args.requirements_file)
                 if args.requirements_file else Requirements(question))
            runner=QuickCouncilRunner(
                transport,events,budget,requirements=req,
                solver=(cfg.solvers[0] if cfg else "gpt-oss"),
                translator_family=(cfg.translator if cfg else "glm"),
                judge_family=(cfg.judge if cfg else "gemini"),
                solver_strategies=(cfg.solver_strategies if cfg else None),
                paper_index=paper_index)
        else:
            runner = CouncilRunner(transport, events, budget,
                solvers=solvers, judge_family=cfg.judge if cfg else JUDGE,
                auditor_family=cfg.auditor if cfg else AUDITOR)
        try:
            result = asyncio.run(runner.run(question, mode=args.mode))
        finally:
            if paper_index is not None:
                paper_index.close()
    if args.json:
        # Include the exact local run ID so offline benchmarks can inspect
        # recorded provider attempts, including failed/retried calls.
        print(json.dumps(dict(result,run_id=run_id),
                         ensure_ascii=False, indent=2))
    elif not args.verbose:
        print_compact_result(result,run_id,args.run_dir)
    else:
        brief = result["research_result"]
        print("\nRun: " + run_id + " | status: " + brief["completion_status"])
        topics=result.get("topic_consolidation") or []
        single_proposal=bool((result.get("role_coverage") or {}).get(
            "single_proposal_assessed"))
        if single_proposal:
            print("Single-proposal mode: RFC topic comparisons are advisory; "
                  "no independent solver cross-review was possible.")
        if topics:
            print("\nBest answer per game (RFC 9381 alignment; advisory, NOT verified):")
            for row in topics:
                topic=row.get("topic","").replace("_"," ").title()
                best=row.get("best_version_id")
                if best:
                    print("- "+topic+" [§"+str(row.get("section"))+"]: "+
                          str(row.get("summary") or "")[:550])
                    print("  Best source-aligned claim: "+best+" — "+
                          str(row.get("best_statement") or "")[:220])
                else:
                    print("- "+topic+": No fully matching version selected.")
                    if row.get("source")=="model_advisory" and row.get("reference_complete"):
                        print("  RFC-based comparison: "+
                              str(row.get("summary") or "")[:550])
                    else:
                        print("  Reference or topic-judge comparison unavailable/incomplete.")
                    if single_proposal:
                        versions=row.get("versions") or []
                        if versions:
                            print("  Single-proposal candidate(s), not independently "
                                  "validated:")
                            for version in versions[:3]:
                                print("   - "+str(version.get("id"))+" ["+
                                      str(version.get("status") or "unjudged")+"] "+
                                      str(version.get("statement") or "")[:950])
                    for partial in (row.get("partial_matches") or [])[:6]:
                        bits=[]
                        agrees=partial.get("agrees") or []
                        conflicts=partial.get("conflicts") or []
                        if agrees:
                            bits.append("right: "+"; ".join(str(x) for x in agrees[:2]))
                        if conflicts:
                            bits.append("wrong/missing: "+"; ".join(str(x) for x in conflicts[:2]))
                        if bits:
                            print("  "+str(partial.get("id"))+" — "+" | ".join(bits)[:600])
                missing=row.get("missing") or []
                if missing:
                    print("  Missing: "+"; ".join(str(x) for x in missing[:3]))
        coverage = result.get("role_coverage")
        if isinstance(coverage, dict) and args.mode == "full":
            expected = coverage.get("requested_solvers", [])
            actual = coverage.get("valid_proposer_families", [])
            audited = bool(coverage.get("independent_audit_completed"))
            print("Full-mode coverage: " + str(len(actual)) + "/" +
                  str(len(expected)) + " valid solver proposals; " +
                  str(coverage.get("review_objection_count", 0)) +
                  " recorded objections; independent audit " +
                  ("completed" if audited else "unavailable"))
        verdict = result.get("verdict")
        if isinstance(verdict, dict):
            detail = verdict.get("cause")
            source = result.get("judge_source", "model")
            label = ("Local evidence verdict" if source == "local_policy"
                     else "Judge verdict")
            human_cause=("definitional answer; no mechanical verification "
                         "possible from game text alone"
                         if detail=="definition_reference_only" else detail)
            print(label + ": " + str(verdict.get("status", "unresolved")) +
                  (" | cause: " + str(human_cause) if human_cause else ""))
        if result.get("final_answer") is not None:
            print("\nEvidence-supported scoped final answer: "+
                  str(result["final_answer"]))
        elif (result.get("answer_selection") or {}).get("answer") is not None:
            selection=result["answer_selection"]
            print("\nSelected scalar ("+str(selection["basis"])+"): "+str(selection["answer"]))
        elif result.get("candidate_answers"):
            print("\nUnverified candidate answers: "+
                  str(result["candidate_answers"]))
        print("\nProposed approach (solver original):\n" +
              (brief["proposed_approach"] or "(none)"))
        if brief.get("judge_summary"):
            source=result.get("judge_source")
            if source=="unavailable":
                print("\nJudge unavailable:\n" + brief["judge_summary"])
            else:
                summary_label = ("Local evidence summary" if
                                 source == "local_policy" else "Blind judge summary")
                print("\n" + summary_label + " (not the solver answer):\n" +
                      brief["judge_summary"])
        print("\nHypotheses:\n" + "\n".join("- " + x for x in brief["hypotheses"]))
        print("\nUnresolved reviewer objections:\n" + (
            "\n".join("- " + x for x in brief["unresolved_objections"]) or "(none)"))
        withheld=result.get("objections_withheld_from_revision") or []
        if withheld:
            print("\nReviewer objections withheld BEFORE author revision "
                  "(advisory RFC/source-scope screening):\n"+
                  "\n".join("- "+str(o.get("id"))+" ["+
                            ", ".join(str(k) for k in o.get("kinds",[]))+"]"+
                            (" §"+str(o["rfc_section"])
                             if o.get("rfc_section") else "")+
                            " — "+str(o.get("issue") or "")[:350]
                            for o in withheld))
        unjudged=result.get("unjudged_objections") or []
        if unjudged:
            print("\nUnjudged objections (not sent to authors):\n"+
                  "\n".join("- "+str(o.get("id"))+": "+
                            str(o.get("issue",""))[:370] for o in unjudged))
        other=result.get("grounded_out_of_scope_objections") or []
        if other:
            print("\nGrounded out-of-scope objections:\n"+
                  "\n".join("- "+str(o.get("id"))+": "+
                            str(o.get("issue",""))[:370] for o in other))
        already=result.get("already_addressed_objections") or []
        if already:
            print("\nObjections already addressed by their cited claim "
                  "(advisory text match; not verified):\n"+
                  "\n".join("- "+str(o.get("id"))+": "+str(o.get("issue"))+
                            " ["+str(o.get("matched_requirement"))+"]"
                            for o in already))
        conflicts=result.get("rfc_conflicting_objections") or []
        if conflicts:
            print("\nObjections that may conflict with RFC 9381 "
                  "(advisory heuristic; inspect before dismissing):\n"+
                  "\n".join("- "+str(c.get("id"))+": "+str(c.get("issue"))+
                            " ["+", ".join(c.get("vrf_warnings",[]))+"]"
                            for c in conflicts))
        advisory = result.get("advisory_findings", [])
        print("\nAutomated security-game warnings (advisory only):\n" + (
            "\n".join("- " + str(item.get("claim_id", "")) + ": " +
                      str(item.get("message", "")) for item in advisory)
            or "(none detected; this does not establish correctness)"))
        audit_advisories=result.get("audit_advisory_findings",[])
        if audit_advisories:
            already={(x.get("claim_id"),x.get("kind")) for x in advisory}
            unique=[x for x in audit_advisories
                    if (x.get("claim_id"),x.get("kind")) not in already]
            if unique:
                print("\nAuditor security-game warnings (advisory only):\n" +
                      "\n".join("- " + str(x.get("claim_id","")) + ": " +
                                str(x.get("message","")) for x in unique))
        references = result.get("reference_checks", [])
        if references:
            print("\nLocal RFC source lookups (provenance only):\n" +
                  "\n".join("- " + item.get("claim_id", "") + ": §" +
                            str(item.get("section", "")) + " — " +
                            str(item.get("reason", "")) for item in references))
        print("\nUnverified claims and proof obligations:\n" + (
            "\n".join("- " + x for x in brief.get("proof_obligations", []))
            or "(none)"))
        print("\nNext actions:\n" + (
            "\n".join("- " + x for x in brief["next_actions"]) or "(none)"))
        print("\nLimitations:\n" + "\n".join("- " + x for x in brief["limitations"]))
        print("\nStructured records saved locally to " + str(args.run_dir / (run_id + ".sqlite3")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
