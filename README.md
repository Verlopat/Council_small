# Council_small — evidence-aware multi-model research council

Implementation of the **Multi-Model Council Architecture v4**, interpreted together with its **Additional Corrections** (pages 33–40). The corrections take precedence where the two disagree: no hunter failure or LLM agreement is treated as a proof, and failed reductions do not automatically disprove the underlying theorem.

The original provider routing foundation comes from the owner's [Verlopat/test](https://github.com/Verlopat/test); that reference repository was not modified.

## Current state

The repository contains a runnable CLI, the original provider adapters, quick/research/full execution modes, typed evidence and claim models, validated role responses, a family-constrained model scheduler, an append-only run log, and offline tests. **Do not equate implemented interfaces with independent live validation.** In particular: formal proof assistants must be installed, bwrap must actually work on the host, billing constraints must be checked on each provider dashboard, and no experiment has yet shown this Council superior to equal-budget best-of-N.

The full pipeline contains sealed independent proposals, a rival claim extractor, peer objections, author revisions, claim-scoped translation and verification, optional counterexample hunters and critics, bounded repair, a blind Gemini-family judge, composition checking and separate auditing. Stage caps and fallback routes are enforced by code. A claim only receives independent arithmetic evidence when its exact asserted equation agrees with the checker input; arbitrary LLM-generated tests and source-quote matches **do not** automatically certify informal claims.

### Feature families

| Area | Main modules | Caveat |
| --- | --- | --- |
| Provider transport and free-tier selection | `model_router.py`, `router_policy.py`, `council/transport.py` | Live availability and free billing depend on your keys and account |
| Family reservations, quotas, deadlines | `council/assignment.py`, `families.py`, `quota.py`, `budget.py` | Set real provider limits in `council.yaml`; unconfigured defaults are not provider guarantees |
| Claims, evidence, reviewer acts | `council/models.py`, `protocol.py`, `evidence.py`, `bus.py`, `moderator.py` | Modalities and proof scope must survive all revisions |
| Claim-specific checking | `council/verify/`, `extract.py`, `translate.py`, `compose.py` | Generated code is NEVER executed without bubblewrap; optional SymPy, Z3, Lean, Tamarin and ProVerif require installation and interpretation review |
| Council workflows | `council/full.py`, `workflow.py`, `judge.py`, `prompts.py`, `schemas.py` | Research outcomes are partial unless evidence justifies the assertions |
| Persistence and replay | `council/events.py`, `replay.py`, `call_cache.py` | Local run logs contain research prompts and provider responses: keep private |
| Evaluation | `eval/` | Plan and run controlled baselines; no published performance results yet |

## Setup

Python 3.11+ and Linux recommended:

```bash
git clone https://github.com/Verlopat/Council_small
cd Council_small
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Add API credentials only for verified free/non-billed accounts.
```

The Council excludes NVIDIA NIM from its family allowlist. OpenRouter candidates are restricted to catalog-confirmed zero-priced `:free` IDs, LLM7 to catalog-marked Turbo eligible IDs. Cohere needs `COHERE_TRIAL_CONFIRMED=1` after confirming a Trial key, and Ollama Cloud needs `OLLAMA_FREE_CONFIRMED=1` after confirming an eligible account. This prevents some accidental paid calls; it **cannot** guarantee what a provider bills.

For isolated model-written check execution, install and verify `bubblewrap`. If unavailable, the checker returns an error. Do not disable this fail-closed behavior.

## Running

```bash
# No API calls: review roles and budget.
python -m council.cli --mode full --dry-run "Investigate lattice VRFs"
python -m council.cli --list-families

# Single solver -> scoped checks -> blind judge -> composition.
python -m council.cli --mode quick --deadline 90 "What security game should a VRF meet?"

# Three proposals -> extracts, reviews, scoped checks, repairs and separate audit.
python -m council.cli --mode full --deadline 600 --json "Design a lattice VRF with ZK proofs"

# Requirements can be supplied as a JSON file with objective, constraints, questions.
python -m council.cli --mode full --requirements-file requirements.json "Research project"

# Replay recorded final result or re-run orchestration from recorded model responses.
python -m council.cli --replay RUN_ID
python -m council.cli --recompute RUN_ID
# Resume missing calls (may consume quota if API providers are configured):
python -m council.cli --resume RUN_ID
```

Customize families and optional features in `council.yaml`. Default three solvers keep an independent Gemma audit family. A fourth Gemma solver is possible if an unused independent family (such as functioning MiniMax) is explicitly assigned the auditor role; do not count the same family twice.

## Evaluation and diagnostics

```bash
# Build 30 original tasks each in numeric, code, symbolic classes (90 total).
python -m eval.generate_tasks --out runs/phase_a_dev.jsonl --split dev --per-kind 30
python -m eval.generate_tasks --out runs/phase_a_holdout.jsonl --split heldout --per-kind 30

# Free, non-executing Phase-A plan:
python -m eval.phase_a runs/phase_a_dev.jsonl --runs 3 --calls 12

# Print evaluation plan; live APIs are disabled unless --confirm-free is passed.
python -m eval.execute runs/phase_a_dev.jsonl --max-tasks 3

# Compare scored Council runs with equal-budget controls:
python -m eval.run_eval runs/eval/results.jsonl
# Aggregate independently supplied blinded research annotations:
python -m eval.score_research ratings.jsonl

# Diagnose provider response fields before treating MiniMax as a seventh usable family.
python -m council.provider_diagnostics
# Weekly-style known-answer regression — no API calls without opt-in.
python -m eval.regression_live
```

The optional GitHub Actions regression schedule is **off by default**. It requires the repository variable `COUNCIL_RUN_LIVE_REGRESSION=true` and secret API keys after you check quotas. Hash changes alone do not establish quality drift; scored regressions do.


## Target-machine security preflight

Before running model-generated checks on the target Linux machine, run:

```bash
python -m council.preflight --json
```

This makes **no API requests**. The preflight uses the existing fail-closed bubblewrap runner to test that an isolated interpreter can run, that outbound network connections are blocked, that host-home directories are not mounted, and that API-key environment variables are absent. It reports optional SymPy and Z3 availability separately. **This is not a comprehensive penetration test or a guarantee of confinement**; check local user namespace policies and mount behavior on the actual host. Do not enable unsafe host execution as a workaround.

Formal proof tool adapters (`lean`, `tamarin`, `proverif`) are now selectable for universal claims when an explicit formal artifact is provided. A successful tool result supports only its submitted formal statement; the original prose and assumptions still require independent correspondence checking.

## Testing

```bash
python -m unittest discover -s tests -v
python -m unittest -v test_simple_router.py
python -m compileall -q council eval
```

Offline tests mock provider responses and exercise invariants; they do **not** certify live access, sandbox deployment, proof soundness or journal research novelty.

## Architecture-v4 completeness

See [IMPLEMENTATION_MATRIX.md](IMPLEMENTATION_MATRIX.md) for the requirement-by-requirement status, limitations, and validation gates. Source architecture includes proposals for future experimental components and ten open questions; some require your account settings, the actual provider responses and qualified human review. No code can truthfully declare those externally dependent results complete.

## Recent feature completion and validation notes (2026-10-30)

The older status checklist was an earlier snapshot. New and connected behaviors include:

- `python -m council.cli --provider-report` shows all eight integrated providers,
  their families, assignment participation, local key configuration and whether
  Cohere/Ollama free-plan confirmation is still required. It does **not** call APIs.
- Model-family first proposals are concurrent; claim-hunter inference is concurrent,
  but the moderator applies responses in a deterministic order to avoid racing writes.
- `council.yaml` solver strategies (`direct`, `code`, `decompose`) and per-thread
  caps are applied in the full workflow and recorded for replay.
- Solver-declared dependencies require an explicit argument and are recorded as
  versioned **unconfirmed** edges until independently checked.
- Similar atomic claims are suggested for review, not automatically merged.
- The assembled numeric verdict is rechecked against a supported literal arithmetic
  claim. A new, unmapped prose assertion stays unchecked.
- A local, licensed paper index is connected to full-mode source checking.
  Passing an exact quote does not imply the paper's statement is true.
- Evaluation defaults to matching the Council's observed number of API calls
  (`--baseline-samples 0`); caps and timeouts are labeled as unmatched. Equal
  call count is **not** equal tokens or equal tool availability.
- Weekly scored model probes distribute requests across endpoints and report
  incomplete coverage. The GitHub Actions workflow requires explicit opt-in
  and an owner-configured `COUNCIL_WEEKLY_MAX_REQUESTS` variable.

### Example commands

```bash
python -m council.cli --provider-report --mode full
python -m council.cli --mode full --dry-run "Evaluate a lattice VRF security game"
python -m council.papers --db runs/papers.sqlite3 --id paper-1 --title "A paper" --license CC-BY-4.0 --text-file paper.txt
python -m council.cli --mode full --paper-index runs/papers.sqlite3 --json "Compare the paper's proof obligations"
python -m eval.execute runs/phase_a_dev.jsonl --max-tasks 3
python -m council.preflight --json
```

To run four independent solvers rather than the default three, configure
`gpt-oss, command, nemotron, gemma`, translator `glm`, judge `gemini`.
Set `auditor: null` when no seventh usable family is available; the output
will explicitly state that independent auditing was not performed. Assign
`auditor: minimax` only after its actual final-answer response has been
verified, and never count a nonworking endpoint as a successful audit.

**Still requiring real validation:** all configured free account quotas and
model identities, target-machine bubblewrap and formal-tool operation,
independent proof/claim alignment, fair token-and-tool-budget benchmarking,
held-out research scoring, interrupted-run recovery, and security testing.
An offline green CI check cannot certify those external conditions.


### Optional hard-deadline inference process

For target Linux deployments that must terminate an in-flight blocking API
request instead of merely cancelling its awaiting thread, set:

```bash
COUNCIL_HARD_DEADLINE=1 python -m council.cli --mode full --deadline 600 \
  "Evaluate a research problem"
```

This opt-in setting launches a separate Python worker for **inference**
and terminates it when its bounded deadline expires. It costs process-startup
overhead and may require local multiprocessing `spawn` permissions. Model
catalog discovery is still performed by the existing bounded thread wrapper,
and the parent wall-clock deadline needs target-host fault-injection testing.
It is an HTTP-liveness mechanism, **not** a sandbox for generated verifier code.
The verifier sandbox still requires bubblewrap and must fail closed.

All 159 tests (141 package + 18 legacy router) passed offline on the
2026-10-30 main-branch CI. Live worker termination, live account quotas,
and formal proof correctness remain external validation gates.

## Checklist fixes and committed evaluation fixtures (2026-10-30)

- SymPy and Z3 solver libraries are in `requirements.txt` for sandbox checkers.
- Failure reasons from the judge are retained rather than overwritten by `blocking_claims`.
- A same-family fallback logs `fallback_selected` with actual endpoint and skipped attempts.
- Debate threads report four deterministic stalemate causes in event history and full output.
- Quick mode respects the first YAML `solvers` entry and the configured translator/judge; the provider report and replay use the same assignment.
- `eval/tasks/dev_research.jsonl` and `heldout_research.jsonl` contain **30 new synthetic scenarios each**, covering missing assumptions (M), invalid proofs (P), literature-overlap judgment (L), incompatible proposals (C), invalid criticisms (V), and open questions (O), five per category per split. Synthetic literature abstracts are explicitly hypothetical.
- `eval/tasks/phase_a_dev.jsonl` and `phase_a_heldout.jsonl` contain **90 fixed-seed tasks each** (30 numeric, 30 code, 30 symbolic). `eval/generate_tasks.py` regenerates these deterministically.
- New regression tests check failure causes, fallback events, stalemate handling, configurable quick mode and split independence. **The manual unittest commands were not run, as requested.** GitHub Actions can still run automatically on push.

The remaining target-machine tasks—installing dependencies, verifying bubblewrap, confirming free API accounts, configuring real quotas, and performing held-out evaluations—are necessary to certify runtime or scientific results. These are not replaced by a successful source commit.
