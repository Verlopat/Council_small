# Architecture v4 + Additional Corrections: implementation audit

**Precedence:** Appendix corrections on pages 33–40 supersede incompatible earlier wording. In particular, `verified_strong` must NOT be inferred from agreement, a failed attack attempt, a passing untrusted test, or a source quote. The program enforces a limited evidence policy; it does not decide mathematical truth.

This table distinguishes **source code included** from **the behavior independently verified**. Statuses: **implemented**, **partial**, **external validation needed**, **open question**.

| Pages / section | Requirement | Code | Status / qualification |
| --- | --- | --- | --- |
| 4–5: principles | Independent first proposals, evidence priority, unresolved outcome | `full.py`, `models.py` | **Partial**: execution enforces basic policy; measurable superiority is unknown |
| 6: providers | Eight free-provider routes, family deduplication, MiniMax diagnostics | `model_router.py`, `families.py`, `provider_diagnostics.py` | **External validation needed**: exact model availability, billing, latency, MiniMax fix |
| 7: agents | Solver, owner/rival extractor, translator, hunter, critic, coverage, relevance, judge | `prompts.py`, `full.py`, `assignment.py` | **Partial**: all role prompts exist; optional roles are switchable; not calibrated |
| 7: reservations | Cross-family claim reviews, judge family isolated, exact model identity | `assignment.py`, `transport.py`, `events.py` | **Implemented in allocated runs**, no claim of statistical independence |
| 8: control plane | Single-writer moderator, flags, bounded reopens | `moderator.py`, `overseer.py` | **Partial**: state writes are by convention in the orchestrator; a formal single-writer process/isolation is not proven |
| 8: quotas | FIFO token buckets, rate headers, three-failure breaker, per-day and shared limits | `quota.py`, `transport.py`, `router_health.py` | **Partial**: verified by offline mocks; real provider limits must be configured |
| 8: deadlines | End-to-end budget and synthesis reserve | `budget.py`, `transport.py` | **Partial**: `asyncio.to_thread` cancellation cannot forcibly stop an in-flight synchronous request |
| 8: injection controls | User and agent text as data, system instructions separate, no tool permission from text | `prompts.py`, `model_router.py`, `transport.py` | **Partial**: this reduces confusion but cannot make prompt injection impossible |
| 9: modes | Quick and full | `full.py`, `cli.py` | **Implemented in code**, live inference not tested in this development session |
| 10: protocol | All named typed speech acts and scoped threads | `protocol.py`, `bus.py`, `moderator.py` | **Partial**: typed checks and caps work; fully asynchronous multi-round claim debates not yet empirically validated |
| 10–11: evidence polarity | Claim/version-matched refs, no unsupported DEFEND/CONCEDE, evidence-gated rounds | `evidence.py`, `moderator.py` | **Implemented for local state updates**; semantic entailment still requires checking |
| 11: caps and dedupe | Message, verifier, repair, pair caps, modal meaning preserved | `bus.py` | **Partial**: conservative text deduplication, not learned semantic equivalence |
| 12: claim states | Corrections: proposed, supported, contradicted, unresolved, withdrawn | `models.py` | **Implemented**; local status is scoped, not a universal proof |
| 13: priority | Deterministic, reproducible choice of uncertain claims | `moderator.py` | **Partial**: precedence adapted to corrected statuses rather than old weak/strong |
| 14: verifier ladder | Rung0 normalization; exact arithmetic; bwrap Python; SymPy; Z3; property/mutation tests; local source quotes; LLM relevance | `extract.py`, `translate.py`, `verify/` | **Partial**: sandbox and formal tool availability not confirmed on user host; natural-language translation needs independent alignment |
| 14: mutation / false positives | Valid/invalid examples and mutants, no automatic universal proof | `verify/python_exec.py`, `verify/mutation.py` | **Implemented logic**, needs real adversarial verifier experiments |
| 15: P0–P6 | Sealed solve, claim extraction, checking, hunts, repairs, blind judge, composition | `full.py`, `judge.py`, `compose.py` | **Partial**: P3/P4 are bounded first implementation, not full asynchronous debate |
| 16–25: code skeletons | Main transport, families, quota, ledger, protocol, evidence, moderator, judge, composition, evaluator modules | `council/`, `eval/` | **Implemented by equivalent modules**, not always identical filenames; v4 snippets were only skeletons |
| 26–27: prompts | Solver, extractor, translator, hunter, judge, structured JSON | `prompts.py`, `schemas.py` | **Implemented** with schema validation and fallback parsing |
| 28: baselines | Single, six-family vote, self-consistency, verifier-selected best-of-N | `eval/baselines.py`, `eval/execute.py` | **Partial**: offline machinery exists; matched live call budgets and scientific outcomes not established |
| 28–29: metrics | False verification, unresolved/no-op, costs, calibration, task-level bootstrap, threshold sweep | `eval/metrics.py`, `eval/parameter_sweep.py`, `eval/run_eval.py` | **Implemented metrics**, no empirical comparisons completed |
| 29: sample grids | 30 original numeric/code/symbolic tasks per class, 3 runs, held-out split | `eval/generate_tasks.py`, `eval/phase_a.py` | **Implemented generator and plan**; execution on providers requires free API budget |
| 29: weekly regression | 20 fixed scored prompts per endpoint; detect performance changes | `eval/regression_live.py`, `.github/workflows/regression.yml` | **Opt-in disabled by default** until provider keys/limits are confirmed |
| 30: failure modes | Missing/invalid evidence, conformity, quotas, sandbox, model drift, overbuilding | Tests, `moderator.py`, `quota.py`, `verify/` | **Partial**: many safeguards are mocked, not independently penetration-tested |
| 31: engineering extras | Pydantic, replay, private keys, response cache, independent tests | `schemas.py`, `replay.py`, `call_cache.py` | **Partial**: response replay is available; production pooling/parallel performance is not evaluated |
| 31: research extras | Paper index, cryptography proof tools, adaptive selection, disagreements | `verify/source.py`, `verify/domain.py`, `ratings.py`, `full.py` | **Partial**: learned routing and real proof tool deployment are research extensions |
| 32: ten open questions | Live quotas, exact API response behavior, primary workload, sandbox choice, publication corpus | `council.yaml`, README, diagnostics | **Open questions**: code cannot know account-specific quota or generate validated science without experiments |
| 33–40: corrected evidence | Scoped evidence, versioned claims, passing test != complete proof | `models.py`, `verify/ladder.py` | **Implemented as conservative policy** |
| 33–40: research output | Hypotheses, obligations, proposed experiments, unresolved objections | `ResearchResult`, `full.py` | **Implemented** |
| 36–38: claim provenance | Source spans, quantifier guards, revisions, dependent re-evaluation | `extract.py`, `models.py` | **Partial**: provenance fields exist; comprehensive dependency-argument graph is not yet validated |
| 38: storage | Run IDs, events, raw and normalized responses, safe replay | `events.py`, `replay.py`, `transport.py` | **Partial**: SQLite events are authoritative; resumability needs fault-injection validation |
| 38–39: research usefulness | Missing assumptions, invalid proofs, literature overlap, incompatible approaches, invalid critiques, genuine open questions | `eval/tasks/research_cases.jsonl`, `eval/research_metrics.py` | **Implemented evaluation rubric**, blinded experts have not scored actual Council responses |
| 39: extra engineering | Explicit objectives/constraints/questions, checked quotas, checkpoints, missing-role reporting | `requirements.py`, `config.py`, `quota.py`, `replay.py` | **Partial**: context partitioning, global checkpoint semantics and usage audits require more validation |

## Hard gates before calling this complete

1. All configured accounts and exact model IDs must be live-tested for free, non-billed inference. In particular, MiniMax must return usable final answers.
2. The supplied host must demonstrate bubblewrap network isolation, resource limits, and real SymPy/Z3/formal-tool execution (not just mocked tests). No execution on host fallback.
3. Claim-to-check semantic alignment, counterexample validity, and provenance must be independently tested on adversarial cryptography tasks. **No research theorem may be labeled proven solely by LLM output.**
4. Real staged evaluations against **equal-call, equal-tool** baselines must be scored on held-out tasks; confidence intervals and false-verified rates must be calculated.
5. The real account quotas and reasonable daily request budgets must be supplied by the user; GitHub cannot infer them.
6. End-to-end cancellation, interrupted-run resume and long-context cases need fault-injection tests on target Linux environment.
7. The full implementation must earn every optional component (coverage, relevance, critics, repair, adaptive seeds) by ablation, not intuition.

No claim of full architectural correctness, independent security verification, or publication-quality improvement is justified until those gates pass.

### Subsequent implementation notes (2026-10-30)

- Added `council/preflight.py`: an offline, fail-closed target-machine check for sandbox execution, network and host-home isolation, and API environment exclusion. It is not a substitute for a host-specific sandbox review.
- Connected optional Lean, ProVerif and Tamarin artifact dispatch to the universal-claim verifier path. Results are tagged as `formal_proof` evidence and **do not** gain independent natural-language claim correspondence by default.
- Added offline regression tests covering formal dispatch and preflight failure paths. CI validates mocked behavior, not actual local namespace or formal-tool availability.
- **Still not complete:** measured correctness against equal-budget baselines, account-specific free quotas and live model inference, formal translation soundness, and host-specific containment validation all remain outstanding.

## Implementation progress after the previous 40-page audit (2026-10-30)

These are code-level changes, not declarations of complete experimental proof:

| Previously partial or missing requirement | Implemented additional behavior | Remaining qualification |
| --- | --- | --- |
| Eight providers | `council/providers.py` and `--provider-report` enumerate all eight and their eligible families | Live keys and free status need confirmation; providers are not eight independent votes |
| Four independent solvers | Four-family configuration supported, with `auditor: null` explicitly reported | Four solvers plus translator, judge, and independent auditor require a seventh usable family |
| Concurrent claim dialogue | Concurrent hunter inference followed by deterministic single-moderator commits; post-repair round evidence-gated | Full unrestricted asynchronous exchange is intentionally bounded by evidence and caps |
| Revision checking | Reviewer follow-up plus scoped rechecking and separate audit | A revised proof remains unproved without independent valid evidence |
| Dependency provenance | `_register_declared_dependencies` records versioned premises and argument text as unconfirmed edges; cycles rejected | A declared argument is never automatically valid support |
| Claim canonicalization | `suggest_duplicate_claims` flags similar claims and records suggestions | No automatic semantic equivalence or unreviewed merge |
| Evidence-backed source retrieval | Full workflow accepts a local `PaperIndex`, records located passage provenance | Quote existence does not certify meaning, truth, or novelty |
| Composition check | Assembled integer recomputation and conservative unmapped-prose detection | Arbitrary multi-module code needs isolated end-to-end tests and specification review |
| Quota and debate settings | Provider report, capped baseline, YAML debate caps, truthful local contention failures | User-owned daily/request/token account budgets remain necessary |
| Evaluation baselines | Default baseline attempts equal API-call count; marks incomplete comparison | Equal tokens/tool budget, multiple seeds and held-out human scoring still required |
| Weekly regression | Endpoints interleaved, partial coverage reported; owner must supply request cap | Live endpoint coverage remains opt-in and quota-dependent |

The full specification contains both *implementable architecture* and
*external validation conditions*. No safe implementation should claim every
requirement completed solely because its file or class exists.


### Hard-stop API lifecycle (additional implementation)

`council/process_infer.py` adds an opt-in spawn-isolated inference process,
selected by `COUNCIL_HARD_DEADLINE=1`. A timed-out worker is terminated
rather than left running as a Python thread. CI checks the selection route
with mocks; the user host still needs a real network-fault timeout test.
It does **not** bound catalog-discovery threads, prove sandbox confinement,
or guarantee provider-side cancellation of a request already accepted.
