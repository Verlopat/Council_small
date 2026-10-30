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

A dry run checks allocation only. If quick mode fails on `proposal/gpt-oss`,
the model may have answered in prose, produced incomplete JSON, or omitted
required proposal fields.

For Council role calls, Groq GPT-OSS now uses low reasoning effort and:
- **Proposals:** strict JSON Schema structured outputs, requiring an approach,
  atomic claims with quoted source spans, hypotheses and experiments.
- **Other roles:** JSON object mode (syntactic only; local validation still applies).
- **Failure handling:** one additional proposal-format attempt, within the same
  family and remaining deadline/free quota. The raw failed answer is never
  inserted as privileged instructions. A second failure returns `unresolved`
  with its actual parser or schema problem rather than a generic label.

These request constraints are supported for Groq GPT-OSS, but **have not
been live-tested on your account**. Other providers remain on their existing
paths. The local coordinator still checks claim anchors and scoped evidence;
correct JSON is not proof of the response's mathematics or security.

A small, opt-in connectivity check remains:

```bash
python simple_router.py --only-provider Groq --retries 0 --timeout 30 --expect 156 "What is 12 multiplied by 13?"
```

Once you `git pull origin main`, retry your real quick question. If it still
returns `unresolved`, the recorded error reason can be inspected safely
from the local `runs/RUN_ID.sqlite3` event log without exposing the model
response, prompts or API keys.

## Interpreting quick-mode claim verification

The quick run produces an unverified research sketch first. It can return
`partial` with `unresolved` claim/verdict status even when the answer sounds
plausible: this is intentional, not proof that the statements are false.

Claims must quote an **exact** span in the original solver's approach or answer.
If the model supplies an incorrect span but its entire claim statement occurs
verbatim in the original text, Council can recover that exact quote. It never
assumes two merely similar sentences mean the same thing. Failed anchoring
records `claim_anchor_rejected` with a safe reason; successful literal
recovery records `claim_anchor_recovered`.

The terminal now labels non-supported statements as proof obligations,
not as reviewer objections. Unverified composed prose remains a blocking
item until appropriately scoped evidence exists. No new cryptographic
security theorem is certified simply because a citation or exact quote
was found.

## Gemini judge JSON, reviewer depth and obligation reporting

For the `gemini` judge family, the `generateContent` request now sets
`generationConfig.responseMimeType="application/json"` and supplies a
judge-specific `responseSchema`. This is a supported legacy
`generateContent` option but is not an assurance that every provider/model
version will return compliant output. Local Pydantic validation remains the
hard boundary. The judgment receives **one** bounded formatting retry after
a successful provider response that cannot be parsed/validated; transport,
quota and deadline failures are not automatically retried.

The user-visible `Run status: partial` means a useful research draft exists,
not that its security claims are verified. The CLI now separately reports the
blind judge verdict and its error cause (if any). Multiple proof obligations
for the same claim ID appear on one row while retaining distinct issues.
A missing challenge proof, a full-vs-trusted uniqueness distinction, and a
claimed hardness reduction are **semantic review questions**: formatting
constraints and literal provenance alone cannot establish their correctness.

For formal cryptography, use `--mode full` and enough verified free
provider quota for independent reviewers, translation and auditing.
`--mode quick` skips independent critics, so "(none)" under reviewer
objections must not be read as a security endorsement.

## Security-game sanity checks and provider failures (October 2026)

The Council may correctly return a **partial** research draft while the blind
judge returns **unresolved**. These are different signals. Literal strings
such as `"null"` from a judge are not substantive summaries; the Council
retains the original solver proposal and records a judge/content warning
instead of replacing that proposal with a `null` placeholder.

If every endpoint for the same translator family fails or the model output
cannot be parsed, later claims in **that run** are explicitly deferred
instead of repeatedly sending the same role to the failed free-tier family.
No previously unverified claim becomes supported. Translation still depends
on a working Z.ai or Cloudflare account.

When a translator reports `output_truncated` and you have confirmed enough
free-token quota, you may explicitly raise only the translator's completion
allowance:

```bash
COUNCIL_TRANSLATOR_MAX_TOKENS=2600 python -m council.cli --mode quick --deadline 180 \
  "Specify a VRF security game"
```

The default remains 1800 tokens; supported range is 256–8192. Increasing
the allowance may consume more of a free allowance and **cannot** fix
timeouts, rate limits or incorrect semantics.

For VRF questions, `council/vrf_sanity.py` performs conservative,
deterministic **advisory** checks for a few explicit game-definition
mistakes: revealing a valid challenge proof in pseudorandomness, replacing
every evaluation-oracle response with random values, conflating full with
trusted uniqueness, using a trapdoor oracle as the definition of trusted
uniqueness, and using a second-valid-output forgery game as the definition
of honest correctness. These are **not** model reviewers, proof checkers,
or complete coverage; absence of flags is not evidence of correctness.
The source distinction is explained in RFC 9381, Sections 3.1–3.4:
https://www.rfc-editor.org/rfc/rfc9381.html

The standalone offline unittest suite remains removed at the owner's
request; these code changes require live owner-machine validation.

## Solver explanations, judge notes, and formatting-only quote recovery

**The solver's original proposed approach is retained.** A blind judge
receives the claims/evidence ledger rather than the full solver answer, so
its `partial_answer` is now stored separately as
`research_result.judge_summary` and printed as "Blind judge summary".
Even a valid judge response cannot overwrite the solver's prose. The
composition checker still treats unsupported prose as unverified.

The source-anchoring stage permits limited formatting variants (Unicode
hyphens and typographic quotation marks, LaTeX relation operators such as
`\\neq` versus `≠`, Markdown math/inline wrappers, and whitespace around
relation operators). It retains the **original exact substring** from the
source answer, its source hash, and the existing quantifier/modality guard.
It does not perform fuzzy matching, case-fold variables, accept paraphrases,
or claim that matching a sentence verifies its semantics. Some claims may
still fail anchoring because their actual content differs from the proposal.

For common VRF game-definition errors, advisory checks now also flag
potentially missing public-key choice in full uniqueness, a reference
challenge output instead of two valid outputs, the wrong ideal
pseudorandomness distribution, and omitted evaluation-oracle/freshness
conditions. Their absence is not evidence of security. See
[local RFC 9381 interpretation notes](references/rfc9381_vrf_games.md)
with links to the official RFC sections. These are *paraphrases*; they are
not automatic theorem validators, nor are they evidence that lattice
reductions have been proved.

```bash
git pull origin main
python -m council.cli --mode quick --deadline 180 \
  "Explain VRF full uniqueness, trusted uniqueness, and pseudorandomness games"
```

## RFC 9381 local reference and low-quota definition checking

RFC 9381 §3 is the reference for the game **definitions**, not a generic
proof that any lattice VRF is secure. To index the complete official RFC on
your machine (with its original copyright and legal notices), run:

```bash
python -m council.rfc_index --db runs/papers.sqlite3
python -m council.cli --mode quick --deadline 180 \
  --paper-index runs/papers.sqlite3 \
  "Explain full uniqueness, trusted uniqueness, and pseudorandomness games of a VRF"
```

The first command explicitly downloads from
`https://www.rfc-editor.org/rfc/rfc9381.txt` and saves the **complete**
document to a local git-ignored SQLite index, not to the repository.
RFC plain-text page headings can say `Request for Comments: 9381` instead
of the contiguous string `RFC 9381`; source validation accepts either
identifier and collapses layout whitespace when checking the title,
sections and copyright notice. If a required marker is absent, the CLI
now names that marker instead of reporting a generic incomplete RFC. It can
also import an already-downloaded official RFC with
`python -m council.rfc_index --text-file /path/to/rfc9381.txt`.
The IETF Trust FAQ allows reproduction of complete RFCs; source text is kept
with its notices. See https://trustee.ietf.org/about/faq/ and consult the
current legal provisions before redistributing excerpts or derivative works.

For recognizable VRF game-definition claims, quick/full mode now **skips
GLM translation**, consults the locally indexed official reference heading,
and records a provenance-only check. A heading match does **not** certify
the definition, prove security, or turn a claim into `supported` or
`contradicted`. A model-generated paraphrase may be wrong despite the
reference being present. Claims of proofs, reductions, implementations and
numeric results still take the normal verification route.

A short redundant conclusion beginning "These definitions capture..." can
be excluded from the VRF claim ledger to avoid an unnecessary translator
call; it remains in the solver's original explanation. The advisory checker
also looks for trusted uniqueness that wrongly demands secret-key secrecy,
"signing oracle" terminology, and uniqueness mistakenly quantified by
the secret key. All heuristic alerts are non-certifying.

**Quick mode now saves a Gemini call by default.** It uses deterministic
ledger-policy judgment, not an LLM review, and labels this distinction in
the CLI. To explicitly run the original blind Gemini judge in quick mode:

```bash
COUNCIL_QUICK_LLM_JUDGE=1 python -m council.cli --mode quick \
  --paper-index runs/papers.sqlite3 --deadline 180 "Explain VRF security games"
```

**Provider policy:** a completed timeout may be retried **once** if there
is enough deadline and a second request is reserved against the quota.
An asyncio thread-cancellation timeout is not retried (the old HTTP thread
could still be running). HTTP 429 `Retry-After` is honored in persistent
health cooldown and the in-process quota scheduler, up to 24 hours.
HTTP 402 (payment/free-credit required) blocks that provider for 24 hours
instead of prompting automatic paid usage. These changes do not grant
additional free allowance or fix exhausted daily quotas. They have not
been live-tested with your provider credentials.

## Quick-mode RFC index routing and sentence-source provenance

As of the latest quick-mode fix, both ordinary `--mode quick` runs and
`--recompute`/`--resume` quick evidence pipelines receive the optional
`--paper-index`. Without this argument, provenance lookup appropriately
reports `No local paper index supplied`. Run:

```bash
git pull origin main
python -m council.rfc_index --db runs/papers.sqlite3
python -m council.cli --mode quick --deadline 180 \
  --paper-index runs/papers.sqlite3 \
  "Explain full uniqueness, trusted uniqueness and pseudorandomness security games for a lattice-based VRF."
```

The default quick-mode verdict is **local policy**; it does not call Gemini.
An unresolved composition therefore reports `composition_failure` (not
`judge_error`). The generated research draft is still unverified.

Groq proposals now include a `sentence_ids` array on each claim. The
solver is prompted to write distinct source lines `[S1]`, `[S2]`, etc.
If its prose quotation differs but the cited numbered lines exist, the
coordinator extracts the **unaltered source text** and records sentence
provenance. This is not proof that the *model-rewritten statement* means
the same thing: the claim is flagged `needs_re_evaluation` and cannot
be independently supported through the ordinary claim verifier until
semantic alignment is resolved. Non-numbered output still uses the
existing strict exact/formatting-only quotation locator.

The VRF advisory checker additionally flags trusted uniqueness that
substitutes compromised *other-identity* keys for the target secret key,
and full uniqueness described as an entirely honest-key game. Per-claim
warnings take precedence over duplicate approach-level warnings for the
same issue. Absence of warnings is **not** a formal game verification.

RFC heading matches establish only that the reference is available,
not that the generated security game is semantically equivalent to it.

## VRF uniqueness vs. collision resistance and Unicode labels

The official RFC 9381 distinguishes different game properties:
**full uniqueness** (Section 3.1) concerns different valid outputs for
one fixed input and one public key; **full collision resistance**
(Section 3.2) concerns the same valid output for two different inputs;
**trusted uniqueness** (Section 3.3) is uniqueness under honestly generated
keys. See https://www.rfc-editor.org/rfc/rfc9381.html#section-3.

The source-definition classifier now treats `full-uniqueness`,
`full‑uniqueness` (nonbreaking hyphen), and `full uniqueness` as the
same *topic label*, including Unicode dash variants, without loosening
claim-source quotation matching or mathematical verification.

Quick-mode VRF advisories now flag claims that call a two-input/
one-output collision a uniqueness attack, descriptions that appear to
verify using secret trapdoors, and full-pseudorandomness games that
randomize the challenge input rather than allowing adversarial target
selection. These diagnostics cannot prove a construction correct or
wrong by themselves.

The quick local evidence summary remains a brief policy statement and
is no longer overwritten with the full solver answer. The Council
still treats unsound or unverified prose as partial/unresolved; RFC
heading checks are source provenance, not semantic entailment.
