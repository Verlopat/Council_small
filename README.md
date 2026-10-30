# Council_small

Evidence-aware, free-API multi-model council for **research proposals, critical review, scoped verification and reproducible evaluation**. Implements the practical core of Architecture v4 with its pages 33–40 corrections: model agreement is **not proof**, and an unsuccessful reduction does not imply a theorem is false.

The independent source router remains in [Verlopat/test](https://github.com/Verlopat/test). This repository contains the Council implementation and an optional standalone interactive router.

## Install

Python 3.11+ and a Linux machine are recommended. The project uses no local NVIDIA model.

```bash
git clone https://github.com/Verlopat/Council_small.git
cd Council_small
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Set keys **only for accounts with a confirmed free/non-billed allowance**. The fixed model allowlist and fallback controls cannot guarantee a provider's billing policy. Cohere and Ollama Cloud additionally require explicit free-tier confirmation flags; account-specific limits belong in `council.yaml`.

## Use

```bash
# No API requests
python -m council.cli --provider-report --mode full
python -m council.cli --mode full --dry-run "Investigate lattice-based VRFs"
python -m council.cli --list-families
python -m council.preflight --json

# Live inference on your configured free-tier accounts
python -m council.cli --mode quick --deadline 90 "Specify a VRF security game"
python -m council.cli --mode full --deadline 600 --json "Propose a lattice VRF with ZK proofs"

# Saved events, recomputation, and resumable inference
python -m council.cli --replay RUN_ID
python -m council.cli --recompute RUN_ID
python -m council.cli --resume RUN_ID
```

`quick` uses the first solver in `council.yaml`, then a translator and blind judge. `full` adds sealed proposals, rival extraction, reviews, revisions, scoped checks, bounded counterexample hunting/repair, judgment, and optional independent auditing. Both can return `unresolved`.

For citations to a provided, licensed **local paper corpus** (passage presence only, not truth):

```bash
python -m council.papers --db runs/papers.sqlite3 --id paper-1 --title "A paper" --license CC-BY-4.0 --text-file paper.txt
python -m council.cli --mode full --paper-index runs/papers.sqlite3 "Analyze the source claims"
```

## Evaluation and monitoring

The `eval/tasks/` folder contains separate fixed-seed development and held-out datasets: **90 numeric/code/symbolic tasks** plus **30 synthetic research scenarios** per split. Keep the held-out split out of model and threshold tuning.

```bash
python -m eval.phase_a eval/tasks/phase_a_dev.jsonl --runs 3 --calls 12
python -m eval.execute eval/tasks/phase_a_dev.jsonl --max-tasks 3
python -m eval.run_eval runs/eval/results.jsonl
python -m eval.score_research ratings.jsonl
python -m council.provider_diagnostics
```

`eval.execute` does not spend API quota without explicit free-tier opt-in. Research benefits require scored held-out trials and fair matched-budget baselines; **no performance superiority is established yet**. The optional GitHub Actions weekly regression is off until `COUNCIL_RUN_LIVE_REGRESSION=true` and a bounded `COUNCIL_WEEKLY_MAX_REQUESTS` are configured.

## Safety and limitations

- **Sandbox:** Generated verification code executes only in fail-closed bubblewrap isolation. Check deployment with `python -m council.preflight --json`. SymPy and Z3 are declared dependencies; Lean/Tamarin/ProVerif are optional external tools.
- **Deadlines:** Set `COUNCIL_HARD_DEADLINE=1` to opt in to process-terminated blocking provider calls; host-level cancellation still needs validation.
- **Evidence:** Executed arithmetic checks, tests, formal statements, and source passages have different scopes. A located quote, accepted formal artifact, or second translator **does not automatically establish the natural-language claim**.
- **Privacy:** `runs/`, response caches and API credentials remain local and ignored by Git. Never publish raw provider headers containing secrets.
- **Unverified external gates:** Live model identity, free quota eligibility, host sandbox behavior, interrupted-request recovery and held-out scientific results.

## Repository layout

`council/` — workflows, model-family routing, evidence, moderation, storage and checks.

`council/verify/` — arithmetic, Python sandbox, symbolic and domain-specific verifiers.

`eval/` — original research task corpora, baseline scoring and opt-in regression.

`model_router.py`, `simple_router.py`, `router_*.py` — functional API adapter and standalone router. `requirements.txt`, `council.yaml` and `.env.example` — dependencies and configuration.

See [Implementation Matrix](IMPLEMENTATION_MATRIX.md) for requirement boundaries.

This working branch is intentionally **production-oriented**: the standalone unit-test suite and its offline-test CI workflow were removed from `main`. They remain recoverable through Git history. Removing tests does not establish correctness or replace deployment validation.

## When quick mode returns unresolved before a proposal

A dry-run verifies role allocation only; it makes **zero** provider requests.
If the quick result reports `proposal/gpt-oss: Groq/...: output_truncated`,
the provider exhausted its completion budget. Council GPT-OSS requests now
select Groq's documented `reasoning_effort=low` for structured role prompts
(the standalone router retains its prior default). You can override this with
`COUNCIL_GROQ_REASONING_EFFORT=medium` or `high` if needed.

Other explicit causes include `empty_final_answer`, `invalid_response`,
`rate_limit`, `auth`, `billing_required`, and `connection`. Do not
paste API keys, private `.env` contents or full provider headers into issues.

Check the standalone Groq adapter with one inexpensive real request:
```bash
python simple_router.py --only-provider Groq --retries 0 --timeout 30 --expect 156 "What is 12 multiplied by 13?"
```
If it succeeds but the Council still fails, the difference is likely the
structured role prompt and its generation limit rather than key connectivity.
Wait for the model's recorded health cooldown to expire before retrying.

