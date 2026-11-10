# Architecture v4 — implementation and evidence status (2026-11-10)

The Appendix corrections override the older weak/strong status policy. **Checked code, a model's opinion, and an actual mathematical security proof are different forms of evidence.** A passing verifier does not automatically establish the correspondence between an English claim and its formal artifact.

| Capability | Implemented | What has actually been demonstrated |
| --- | --- | --- |
| Free-only provider routing, independent proposals, judge, reserved audit | `model_router.py`, `council/families.py`, `council/full.py` | User-run VRF definition experiment; provider availability, lineages and billing require recurring account confirmation |
| Full and quick definition mode | `council/cli.py`, `council/definition_sources.py`, `council/judge.py` | Five quick and five full **live** VRF definition runs completed before these mechanical-check changes: 8 and 134 completed responses respectively, with 8 and 161 logged attempts and 11 full-mode advisory picks; manual correctness comparison not yet scored |
| Reference-grounded VRF objections and cross-game anchors | `council/objection_sections.py`, `council/vrf_audit.py`, `council/full.py` | Offline regression tests cover known misclassifications; quote matching and model verdicts remain advisory |
| Independent verifier translator with fallback | `council/full.py`, `council/translate.py` | Offline simulated first-family failure and independent fallback; **not demonstrated live for checkable claims** |
| Author-generated optional self-checks | `council/schemas.py`, `council/structured.py`, `council/verify/author_check.py`, `council/verify/python_exec.py` | Print-value recomputation and old JSON pass/fail self-tests run only inside fail-closed bubblewrap; evidence always nonindependent; self-inconsistent code blocks verified reporting even if a separate checker passes |
| Actual checkers (numeric, SymPy, Z3, Python, mutation, optional formal) | `council/verify/`, `council/preflight.py` | Arithmetic aliases (expected_int etc.) and symbolic lhs/rhs aliases accepted with conflict validation. Offline unit tests pass; deployment bwrap preflight and live checker performance still require user-machine validation |
| Scalar answer claims and evidence-gated final answers | `council/schemas.py`, `council/final_answers.py`, `council/full.py` | Proposals explicitly return final_answer; labeled fallback extraction handles inline numeric/boolean answers. Quick prioritizes at most one translator attempt for answer claims. Only question-literal arithmetic can be independently aligned automatically; unaligned word-problem translations remain unverified |
| Bounded evidence, versioned ledger and debate | `council/models.py`, `council/moderator.py`, `council/ledger.py` | Offline regression tests; proof-to-English alignment and universal claims still unresolved |
| Source-free disagreement report | `council/full.py`, `council/cli.py` | Competing claims/reviewer objections recorded, never marked proved |
| Per-provider quota controls and pacing | `council/quota.py`, `council/transport.py`, `council/config.py` | Provider-shared TPM/RPM queue; **actual free limits must be entered by the account owner**. Unconfigured 30-RPM pacing is protective, not a provider guarantee |
| Evaluation metrics and baselines | `eval/execute.py`, `eval/metrics.py`, `eval/run_eval.py`, `eval/compare_repeated_modes.py` | Selected accuracy distinguished from verified accuracy, false verification and candidate-oracle upper bound; gold-assisted best-of-N excluded from fair baselines; code scores may be ungraded. Repeats are bootstrapped by **distinct tasks**, not individual model calls. No completed independently reviewed live Phase-A evaluation yet |
| Phase-A tasks and sandbox-only hidden code scoring | `eval/generate_tasks.py`, `eval/code_tasks.py`, `eval/tasks/phase_a_dev.jsonl`, `eval/tasks/phase_a_heldout.jsonl` | Two disjoint sets of 90 original-generated numeric/code/symbolic tasks, including 30% false symbolic identities; hidden Python cases execute only through bubblewrap and never select a baseline. Code-task accuracy is ungraded when the sandbox is unavailable |
| Research-task evaluation and annotation | `eval/research_metrics.py`, `eval/tasks/dev_research.jsonl` | 30 development cases available, but no recorded independently scored live research evaluation |
| Role and timeout policy | `council/assignment.py`, `council/full.py`, `council/transport.py`, `council/cli.py` | Primary translator may fall back only to permitted nonowner families, never judge/auditor; actual configured role reservation validated. Explicit --timeout caps a request; unset --deadline inherits YAML default |
| Repeated experiment isolation | `scripts/benchmark_vrf_modes.sh`, `scripts/benchmark_phase_a_modes.sh`, `eval/run_manifest.py` | A run directory is bound to Git revision, input hashes and settings; completed results are never overwritten, and interruption leaves inspectable partial files |
| Replay, structured events, SQLite | `council/events.py`, `council/replay.py` | Offline tests; full interruption/resume recovery still needs real testing |

## Latest Phase-A fixes (2026-11-10)

- Groq/Cohere baseline calls now use plain-text response mode rather than
  requiring JSON for a natural-language prompt. Structured proposal roles
  retain their strict provider schemas.
- Reworded claims with a source passage may reach the translator, but
  unproven source-to-claim alignment continues to prevent certification.
- A nonempty scalar final_answer is required by the strict proposal schema;
  locally revalidated old/replayed proposals remain backwards-compatible.
- Rate limits remain owner-configured in council.yaml. Placeholder free-tier
  quotas are never installed or portrayed as real provider allowances.
- An observed passing author self-test, or a translator-provided expression
  that only happens to equal the answer, does not automatically count as
  independent evidence. At least one verified answer in a small smoke run
  is NOT an invariant: it depends on a genuinely alignable question.

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
5. User's local Phase-A evaluation attempt crashed while grading an empty vote; this is regression-protected, but a complete live comparison has **not** been demonstrated. The assistant has not run live provider-backed Phase-A or an actual user-machine sandbox preflight.
6. The historical regression suite and GitHub Actions checks are present on `main` and run on Python 3.12 and 3.14, including compilation and Bash syntax checks. Passing tests do not certify live provider behavior.
