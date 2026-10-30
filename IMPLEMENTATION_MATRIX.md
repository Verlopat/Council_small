# Architecture v4 — implementation boundaries

The Appendix corrections (pages 33–40) override the early weak/strong status policy. Code enforces an evidence policy; it does not decide mathematical truth.

| Requirement | Implementation | Remaining validation |
| --- | --- | --- |
| Eight free-tier provider routes and family-aware fallback | `model_router.py`, `council/families.py`, `transport.py`, `providers.py` | Provider identity, rate limits and zero billing must be checked with real accounts |
| Independent proposals, role reservation and blind judge | `assignment.py`, `full.py`, `judge.py` | Four independent solvers may require `auditor: null` unless a seventh working family is available |
| Owner/rival claim extraction, assumptions and quantifiers | `extract.py`, `schemas.py`, `models.py` | Models can miss implicit assumptions or invalid implications |
| Cross-family review, author response and review of revisions | `full.py`, `protocol.py`, `prompts.py` | Reviews are not independent proof |
| Claim states, versioned evidence and dependency records | `models.py`, `dependencies.py`, `ledger.py` | Premise-edge validity must be independently established |
| Conservative duplicate suggestions | `extract.py` | Similarity never automatically merges claims |
| Scoped arithmetic, SymPy, Z3, Python, mutation and formal tools | `council/verify/`, `preflight.py` | Bubblewrap, packages and formal tools must work on the real host; proof-to-prose translation requires separate checking |
| Typed debate, round gating, caps and four stalemate outcomes | `bus.py`, `moderator.py`, `evidence.py`, `overseer.py` | Full asynchronous behavior and robustness require practical evaluation |
| Rate buckets, quota accounting and bounded requests | `quota.py`, `transport.py`, `budget.py`, `process_infer.py` | Configure actual account request/token caps and validate cancellation |
| Quick, research and full modes | `cli.py`, `workflow.py`, `full.py`, `config.py` | Real provider runs and missing-role degradation must be observed |
| Composition check and partial verdict | `compose.py`, `judge.py` | Arbitrary code-composition security is not mechanically proved |
| SQLite+JSONL persistence, response cache and replay | `events.py`, `replay.py`, `call_cache.py`, `ledger.py` | Interruption and multi-process crash/recovery validation outstanding |
| Local source passages and research output contract | `verify/source.py`, `papers.py`, `models.py` | Source passage presence does not establish truth or novelty |
| Equal-budget baselines, phase-A and research evaluation | `eval/execute.py`, `eval/phase_a.py`, `eval/research_metrics.py`, `eval/tasks/` | Need held-out scored experiments, confidence intervals and token/tool-budget comparisons |
| Weekly model-quality monitoring | `eval/regression_live.py`, `.github/workflows/regression.yml` | Disabled pending owner opt-in and explicit request cap |

## Hard gates

1. Validate actual free accounts, model outputs, identities and rate-limit headers.
2. Verify sandbox network/file-system isolation and SymPy, Z3 and optional proof tools on the target machine.
3. Independently audit the correspondence between natural-language claims and executable/formal artifacts.
4. Evaluate false positives, missed objections, useful repairs, latency, tokens and cost against fair baselines, using untouched held-out scenarios.
5. Verify deadlines and resume behavior under actual transport faults and interruptions.

## Clean repository policy

Only active runtime, configuration, docs, evaluation and **opt-in scored regression** components remain on `main`. Standalone unit-test files and their automatic test workflow have been removed at the user's request. Previous test history is still accessible in Git; the absence of the tests is not a claim of security or mathematical correctness.
