# Architecture v4 — current implementation and evidence status (2026-11-09)

The Appendix corrections override the older weak/strong status policy. **Checked code, a model's opinion, and an actual mathematical security proof are different forms of evidence.** A passing verifier does not automatically establish the correspondence between an English claim and its formal artifact.

| Capability | Implemented | What has actually been demonstrated |
| --- | --- | --- |
| Free-only provider routing, independent proposals, judge, reserved audit | `model_router.py`, `council/families.py`, `council/full.py` | User-run VRF definition experiment; provider availability, lineages and billing require recurring account confirmation |
| Full and quick definition mode | `council/cli.py`, `council/definition_sources.py`, `council/judge.py` | Five quick and five full **live** VRF definition runs completed before these mechanical-check changes: 8 and 134 completed responses respectively, with 8 and 161 logged attempts and 11 full-mode advisory picks; manual correctness comparison not yet scored |
| Reference-grounded VRF objections and cross-game anchors | `council/objection_sections.py`, `council/vrf_audit.py`, `council/full.py` | Offline regression tests cover known misclassifications; quote matching and model verdicts remain advisory |
| Independent verifier translator with fallback | `council/full.py`, `council/translate.py` | Offline simulated first-family failure and independent fallback; **not demonstrated live for checkable claims** |
| Author-generated optional self-checks | `council/schemas.py`, `council/structured.py`, `council/verify/python_exec.py` | Scripts execute only inside fail-closed bubblewrap; evidence always marked nonindependent; mutation checks require positive and negative fixtures |
| Actual checkers (numeric, SymPy, Z3, Python, mutation, optional formal) | `council/verify/`, `council/preflight.py` | Offline unit tests, **not yet preflight-verified on user's machine**; missing bwrap cannot trigger unsafe host execution |
| Candidate vs evidence-supported final answers | `council/final_answers.py`, `council/full.py` | Conservative numeric/boolean extraction and offline support gating; candidates explicitly unverified |
| Bounded evidence, versioned ledger and debate | `council/models.py`, `council/moderator.py`, `council/ledger.py` | Offline regression tests; proof-to-English alignment and universal claims still unresolved |
| Source-free disagreement report | `council/full.py`, `council/cli.py` | Competing claims/reviewer objections recorded, never marked proved |
| Per-provider quota controls and pacing | `council/quota.py`, `council/transport.py`, `council/config.py` | Provider-shared TPM/RPM queue; **actual free limits must be entered by the account owner**. Unconfigured 30-RPM pacing is protective, not a provider guarantee |
| Evaluation metrics and baselines | `eval/execute.py`, `eval/run_eval.py` | Selected accuracy distinct from verified accuracy, false-verified rate, and candidate-oracle upper bound; paired task-bootstrap CI, per-kind quick/full comparison; **no checkable-task live Phase-A results yet** |
| Phase-A tasks and sandbox-only hidden code scoring | `eval/generate_tasks.py`, `eval/code_tasks.py`, `eval/tasks/phase_a_dev.jsonl`, `eval/tasks/phase_a_heldout.jsonl` | Two disjoint sets of 90 original-generated numeric/code/symbolic tasks, including 30% false symbolic identities; hidden Python cases execute only through bubblewrap and never select a baseline. Code-task accuracy is ungraded when the sandbox is unavailable |
| Research-task evaluation and annotation | `eval/research_metrics.py`, `eval/tasks/dev_research.jsonl` | 30 development cases available, but no recorded independently scored live research evaluation |
| Replay, structured events, SQLite | `council/events.py`, `council/replay.py` | Offline tests; full interruption/resume recovery still needs real testing |

## Mandatory local prerequisite

Install only when needed and on your own machine, then inspect actual results:

```bash
sudo pacman -S bubblewrap
python -m pip install -r requirements.txt
python -m council.preflight --json
```

Preflight must report **pass** for sandbox execution, network isolation, home isolation, and environment isolation. Any failure means generated code must remain unexecuted. Optional SymPy/Z3 availability and proof tools require separate inspection.

## Live evaluation (opt-in only)

```bash
python -m eval.execute --tasks eval/tasks/phase_a_dev.jsonl --mode quick --max-tasks 30 --out runs/eval_quick --confirm-free
python -m eval.execute --tasks eval/tasks/phase_a_dev.jsonl --mode full --max-tasks 30 --out runs/eval_full --confirm-free
python -m eval.run_eval runs/eval_quick runs/eval_full
```

Inspect `python -m eval.execute --help` and run without `--confirm-free` first to see the request estimate. The two systems must be compared on equivalent tasks; paid quota, provider overload, missing tool privileges, unequal baseline calls, and token use are methodological caveats. Do not use heldout to tune thresholds.

For research evaluations, complete blinded human annotations using `eval/research_metrics.py`; no automatic model opinion replaces human scientific review.

## Security and reporting boundaries

1. A model-written self-check is recorded only as **unchecked author evidence**, never independent support.
2. Passing a bounded local checker proves only its declared scope, not an unrestricted theorem or an RFC security property.
3. Exact RFC quotation matching is retained rather than approximate semantic matching that could accidentally normalize away critical quantifiers.
4. Review claims and objections remain audit-visible, including unjudged or quote-rejected items.
5. No live provider-backed Phase-A, research evaluation, or local bwrap preflight has been run by the assistant.
6. The historical core regression suite and automated GitHub Actions tests are present again on `main`; prior text claiming they were removed was stale.
