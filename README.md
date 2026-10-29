# Multi-Model Council (Council_small)

An evidence-aware, research-oriented multi-LLM council running over **allowlisted free-tier API models**. Based on `Council_Architecture_v4` and, importantly, the **Additional corrections** at the end of that document.

The API connector, model catalog checks, fallback policy, health cache, and their offline tests were imported from the owner's [Verlopat/test](https://github.com/Verlopat/test). That repository is unchanged.

## Implemented initial milestone

- 8 configured API providers from the reference router (no NVIDIA in Council roles)
- Model **family** assignment (not endpoint voting), same-family failover, reserved Gemini synthesis role
- Sealed first proposals: **gpt-oss / Command / Nemotron** cannot see one another before proposing
- Structured cross-family objections; author revisions and versioned claim records
- Independent **GLM final audit**, separate from all proposer and synthesis families
- Conservative research brief: hypotheses, proof obligations, objections, experiments and next steps
- A model's claims are **not** promoted to verified because models agree or fail to refute them
- SQLite + JSONL local event history, replay of recorded final report, prompt hashes and actual model identities
- Deadline with synthesis reserve, deterministic partial output on missing or failing roles
- Safe, narrowly scoped arithmetic checker (never runs generated Python on the host)
- Offline integration tests in GitHub Actions

### What is **not yet** implemented

This is a **first end-to-end research milestone**, not the entire v4 architecture. No raw provider response/headers API yet; the inherited router returns text. No retrieval verification, automatic source checking, bubblewrap execution of model-generated code, formal proof translation, asynchronous claim debate bus, adaptive seeds, calibrated role ratings, or evaluated superiority over best-of-N. The arithmetic checker is presently a library utility, not an automatic proof of Council-generated claims. Accordingly, the orchestrator always leaves unsupported findings as **hypotheses**, and labels its final report **partial**.

The first target is reliable *research idea generation and critique*, not automatic theorem certification.

## Set up

Python 3.11+ recommended:

```bash
git clone https://github.com/Verlopat/Council_small
cd Council_small
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Edit .env locally and add ONLY confirmed free/non-billed API keys.
```

Never commit `.env` or share credentials. **Cohere requires a confirmed Trial key** and `COHERE_TRIAL_CONFIRMED=1`; Ollama Cloud requires confirmation of a free non-billed plan and `OLLAMA_FREE_CONFIRMED=1`. Keys alone do not prove no payment will occur. OpenRouter candidates are re-checked for `:free` and zero token prices; LLM7 candidates are limited to catalog-marked Turbo allowance. Recheck billing limits yourself before real calls.

## Commands

```bash
# No API calls; plan the allocation.
python -m council.cli --dry-run --mode research "Explore lattice-based VRFs"
python -m council.cli --list-families

# Two roles: one solver then synthesis. Still an unverified research sketch.
python -m council.cli --mode quick --deadline 90 "Sketch a threshold VRF"

# Research first milestone: 3 proposals, cross review, revision, synthesis and audit.
python -m council.cli --mode research --deadline 300 --json "Design a lattice VRF with ZK verification"

# Replay the stored result with no API calls (copy the run_id printed by CLI).
python -m council.cli --run-dir runs --replay RUN_ID

# Offline tests; uses mock provider responses.
python -m unittest discover -s tests -v
python -m unittest -v test_simple_router.py
```

The router's original utilities are still available: `python model_router.py --list`, `python simple_router.py --check-providers ...`. **Live provider health was not re-tested during this implementation.**

## Responsibility and limitations

The control code enforces evidence policy; it does not make uncertain natural language claims true. Model suggestions are never evidence of execution. A negative review is not a verified counterexample; a conceded proof gap does not imply a theorem is false. Changing a claim increments its version and forces evidence reconsideration. A disproved premise requires reconsidering dependents rather than declaring conclusions false.

Family diversity is useful for reducing duplicated perspectives, but does not prove independent errors. Tagged/serialized prompts reduce accidental role confusion but are not a prompt-injection security boundary. The inherited synchronous requests use bounded async wrappers; cancellation cannot forcibly terminate a thread already inside a network request. Full raw-response, header-aware quota scheduling and a hardened execution sandbox are future implementation tasks.

Local run logs **contain research questions and model responses**; keep `runs/` private. Only run trusted code yourself. No model-generated Python is executed by this version.

## Next milestones

1. Raw JSON/header transport, endpoint-specific token budgets and quotas, robust deadline enforcement.
2. Mechanically checked claim artifacts in an isolated, network-disabled sandbox, mutation and specification tests, source retrieval.
3. Deterministic debate protocol and separate critique/revision validation, dependency re-evaluation.
4. Equal-budget evaluation against single-model, self-consistency and tool-selected best-of-N baselines; use held-out research and code tasks.

The reference `test` repository remains a transport reference, not the deployment target.
