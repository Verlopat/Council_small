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

`quick` uses the first solver in `council.yaml` and a scoped verification path; its default verdict uses local evidence policy without a paid/quota-consuming model judge (enable the optional judge via `COUNCIL_QUICK_LLM_JUDGE=1`). `full` adds sealed proposals, rival extraction, reviews, revisions, scoped checks, bounded counterexample hunting/repair, judgment, and optional independent auditing. Both can return `unresolved`.

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

## Two-repeat verification (November 2026)

Before any live evaluation, `python -m council.preflight --json` must
pass execution, network, home and environment isolation checks. No sandbox
preflight result proves that an arbitrary cryptographic claim is correct.

For **two new VRF security-game quick/full pairs** with separate results
(and no overwriting of the previous five-pair run):

```bash
git pull origin main
RUN_DIR=runs/vrf_verify_nov10 COUNT=2 bash scripts/benchmark_vrf_modes.sh
python -m eval.compare_vrf_modes --input-dir runs/vrf_verify_nov10 --count 2 \
  --scores runs/vrf_verify_nov10/vrf_human_scores.csv
```

Grade the three definitions **manually** in the generated CSV using RFC 9381.
The model's advisory selections do not count as independent correctness.

For a **two-repeat Phase-A comparison** covering the first numeric, code and
symbolic tasks, with no extra self-consistency or vote6 baseline API calls:

```bash
RUN_DIR=runs/phase_a_verify_nov10 COUNT=2 MAX_TASKS=3 \
  bash scripts/benchmark_phase_a_modes.sh
python -m eval.compare_repeated_modes --root runs/phase_a_verify_nov10 --count 2
```

Both scripts check isolation and avoid overwriting completed runs. By default
they pace separate live jobs by 90 seconds; set `PAUSE_SECONDS` to an
account-appropriate value. Repeated attempts measure stability but are
**correlated**, not two new independent benchmark tasks. Always confirm your
actual provider free quotas before using `--confirm-free`.

Phase-A evaluation uses the configured roles, with `--no-baselines` to
avoid multiplying the provider calls. If independent baselines are enabled,
gold-derived arithmetic best-of-N is an **oracle-assisted bound**, excluded
from fair paired accuracy comparisons. Hidden Python implementation tests
run only through bubblewrap; absence of a trusted sandbox means ungraded
code correctness, not a passing result.

## Phase-A scalar-answer and check-path smoke test (November 10)

Phase-A proposals now have a strict `final_answer` field for scalar results.
Final-answer extraction also accepts a labeled value inside a sentence;
baseline requests use plain text rather than Groq JSON mode. Reworded
source-anchored claims can be checked, but source-to-claim semantics remain
unverified. Author-written Python may print the proposed scalar and is checked
only in the isolated sandbox. Matching the author's own result is **not
independent support**. Quick mode prioritizes one answer translation attempt.

Before testing, run `python -m council.preflight --json` and ensure
execution, network, home and environment isolation all pass. Use a new output
directory to prevent overwriting an earlier, partially completed experiment.

```bash
git pull origin main
python -m council.preflight --json
python -m eval.execute --tasks eval/tasks/phase_a_dev.jsonl \
  --mode full --max-tasks 3 --deadline 1200 \
  --baseline-samples 2 --skip-vote6 \
  --out runs/phase_a_scalar_smoke_nov10 --confirm-free
python -m eval.run_eval runs/phase_a_scalar_smoke_nov10 \
  --baseline self_consistency
```

`--skip-vote6` suppresses the six additional family-vote API calls while
retaining the single-model and self-consistency baselines. The full two-repeat
quick/full script uses `--no-baselines` to avoid all extra baseline calls.

An arithmetic answer may be independently verified only when the exact
calculated expression can be grounded in the original question and recomputed.
For word problems the model-translated expression is **not** independent
semantic validation; `correct_verified` can legitimately remain zero even
when the predicted result matches the benchmark's hidden reference.
Blindly forcing a positive verified flag is explicitly disallowed.

## Quota and evaluation corrections (November 11)

Shared daily counters roll over once per provider account, including when
several model endpoints are used after midnight. Queue waiting and catalog
lookup consume the endpoint timeout; retries recheck the remaining deadline
after quota waiting. Partial token reports retain the conservative reservation,
and observed TPM overages remain debt until replenished. Configuration rejects
nonfinite rates and fractional burst sizes.

Phase-A call counts include retries and failed baseline requests. A retry is
recorded only after its quota reservation succeeds, immediately before dispatch.
Older run databases may include scheduled retries that never dispatched; rerun
evaluations to use the corrected accounting. Equal call counts still do not mean
equal tokens or provider charges. These changes have offline regression coverage;
provider-account behavior and sandbox isolation require local validation.

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

The offline regression suite and GitHub Actions unit-test workflow are present on `main`. Tests check orchestration contracts, not live provider correctness or mathematical theorem validity.

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

The standalone offline unittest suite is restored and runs on every push to
`main`. Provider- and sandbox-dependent behavior still needs validation
on the owner's machine.

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

## Full-mode review coverage and VRF definition regression (October 2026)

A `--mode full` run can still return `partial` when free providers do
not respond or when required roles cannot run. It must not imply that
three independent solvers and the reserved auditor completed their work.

Use `python -m council.cli --provider-report --mode full` first.
The report includes `active_attempt_eligible_families` and
`active_not_ready_families`, and per-provider
`eligible_for_attempt`. These mean only that an API key and any
required local non-billed/free-mode confirmation are present. They are
**not live connectivity or quota checks**.

Cohere's solver family requires `COHERE_TRIAL_CONFIRMED=1` and
Ollama Cloud's auditor requires `OLLAMA_FREE_CONFIRMED=1` in the
environment **only if you have independently confirmed usable free
allowances with no unexpected charges**. Never set either flag blindly
or assume the service has a particular remaining quota. If a family
is unavailable, the Council preserves reservations and reports the
result as reduced independent proposal coverage or missing audit,
rather than silently assigning an already-used judge or solver to
that role. The structured output includes `role_coverage`.

For multiple successful solver families, the CLI separates the
original proposals and identifies their family, so mutually inconsistent
answers are not merged into one undifferentiated paragraph.
Automated checks examine numbered VRF source sentences individually.

The RFC 9381 definition router now recognizes definitional statements
such as "Full uniqueness requires..." and "Trusted uniqueness
assumes...", even when the word "game" is omitted. It still never
upgrades a claim to supported just because a source heading is found.
Claims about a concrete scheme's security reductions do **not** get
mistaken for a definitional citation.

Security-game red flags now distinguish VRF uniqueness (a fixed input
and two different accepted outputs) from collision resistance (two
different inputs and the same accepted output). A statement demanding
different outputs for *all* distinct inputs is likewise a
collision-resistance/injectivity condition, **not** a definition of
uniqueness. They also distinguish an honest-key-only statement from
full uniqueness. These remain incomplete heuristic advisories; an
absent warning or a model's reviewer objection does not constitute
a cryptographic theorem or independent verification.

## Provider resilience and guarded full-mode execution

**Cohere Command / Chat v2:** Proposal requests now explicitly send the
documented `response_format={"type":"json_object","schema":...}` schema.
Local strict Pydantic validation still runs. For provider near-misses only,
`approach` as a list of strings becomes a newline-joined string, and
`assumptions`, `limitations`, `depends_on`, `hypotheses`, and
`experiments` accept a single string as a one-item list. Other types still
fail. The JSON Schema request follows the current official API docs:
https://docs.cohere.com/v2/docs/structured-outputs .

**Nemotron and other slow reasoning endpoints:** Without an explicit timeout,
the transport may use a longer configured per-endpoint allowance (currently
up to 110 seconds for Nemotron and 120 seconds for Command). An explicit
`--timeout 60` is now a **strict per-call ceiling**: it must not be
silently raised by an endpoint default. The total run deadline is separate. A *completed*
truncation on these roles can retry once using up to twice the prior
output-token allowance (capped at 16,384), with another request reserved
against the configured quota. Provider caps may be lower; an increased
request is not guaranteed to succeed.

**Transient errors:** A completed server, connection or timeout response
may retry once when enough global deadline remains. Server retries pause
4 seconds. For a Gemini judge 5xx error, the one retry removes the structured
response schema as a diagnostic fallback. If all eligible judge endpoints
fail, output says `Judge unavailable`, not an invented Gemini summary.
The sanitized event log includes error kind and, when exposed by the
HTTP adapter, numeric HTTP status. No raw error bodies are persisted.
To disable Gemini's judge schema *from the initial request* for diagnosis:
`COUNCIL_GEMINI_JUDGE_SCHEMA=0 python -m council.cli ...`.
This option is NOT a way to bypass local validation or billable limits.

**Insufficient independence:** When full mode receives fewer than two
valid independent solver proposals, it returns
`verdict.cause="insufficient_independence"` immediately after the sealed
proposal stage. It preserves ledger claims, RFC provenance and advisory
warnings but does **not** call the expensive review, repair, judge or
audit stages. The next actions distinguish missing free-access
confirmation, invalid proposal structure and provider inference failures.

**Answer quality:** On explanatory tasks, a solver proposal consisting
mostly of steps to do later (e.g. "Define...", "Outline...", "Propose...")
is rejected with a bounded format retry. Neither plans nor simple provider
agreements are counted as verified scientific results.

**Auditor hygiene:** The auditor receives solver-authored propositions,
source spans, evidence status and reviewer objections, not the
coordinator's generated obligation explanations. Auditor VRF objections
receive their own advisory sanity scan, including the difference between
a public VRF proof for an ordinary input and the challenge output *without*
a proof in RFC 9381 Section 3.4. Original objections are preserved; a
sanity warning cannot by itself disprove the auditor.

**VRF advisory deduplication:** Evaluate the structured claims first,
then inspect only original approach sentences not covered by claim source
anchors. Additional flags cover omitted secret-key knowledge in trusted
uniqueness and an impossible pseudorandomness challenge asserted to occur
"in each game." These checks are incomplete pattern matching, NOT formal
security-game equivalence checking.

For an offline-only provider readiness check:

```bash
python -m council.cli --provider-report --mode full
```

For a complete Council attempt after confirming actual free-provider access:

```bash
python -m council.cli --mode full --deadline 1200 --timeout 60 \
  --paper-index runs/papers.sqlite3 \
  "Explain full uniqueness, trusted uniqueness, and pseudorandomness security games for a lattice-based VRF."
```

The diagnostic run may legitimately stop with
`insufficient_independence` or `unresolved`; that is preferable to
spending quota while silently asserting unsupported proofs.

## Compact judge comparisons and cleaner extraction (November 2026)

A successful `--mode full` proposal stage may create more claims than a
6,500-character blind ledger can contain. The blind judge now receives a
topic-grouped, capped (12,000-character) presentation containing claim IDs,
bounded statement text, verification status, scoped evidence summaries,
advisory warning kinds, the *complete list* of blocking claim IDs, and
explicitly listed omitted IDs when compression is necessary. The original
ledger and evidence remain unchanged. If essential flagged records cannot
fit, the judge is SKIPPED with `judge_input_too_large`; no placeholder text
is passed off as the ledger.

For VRF questions with the official `rfc9381` in
`--paper-index`, the judge input additionally includes short **verbatim**
excerpts from RFC 9381 Sections 3.1, 3.3, and 3.4, marked by section,
source URL and document digest. The judge is instructed to compare the
claim versions per topic and name the best textual match or *none*.
**Neither an RFC heading lookup nor a model's comparison constitutes
semantic verification, cryptographic security or proof of a lattice VRF.**

The rival extractor records and skips clearly redundant source claims
under the event `rival_claim_duplicate_skipped` and their original
`duplicate_of` IDs; it does not merge evidence. Self-referential
statements beginning "The answer", "The response", "The proposal" and
similar phrases are removed from the verifier queue. Unnumbered and
single-line `[S1] ... [S2] ...` plan lists are rejected when the user
requested an explanation. A request-specific HTTP 400
`request_invalid` does not poison the endpoint's persistent health, so
an author's subsequent revision is not blocked by that health record.
The underlying 400 still needs diagnosis; malformed inputs are not retried
automatically as if they were provider outages.

Nemotron endpoint token allowances also apply to **review** calls.
Hunter near-miss JSON with object/list details is serialized without
changing the values' meanings; model instructions still request a
counterexample string and a string list of tried steps.

VRF advisory checks now distinguish different *proofs* from different
*VRF output values*, flag key-secrecy restrictions in trusted uniqueness,
and flag pseudorandomness games that alter ordinary oracle answers or
introduce unnecessary verification oracles. Both original solver source
excerpts and condensed claims are checked for known mistakes without
duplicating a warning kind within one proposal.

Repair requests include the claim's applicable VRF warnings and, where
available, the official bounded RFC excerpt. Repairs remain new,
unverified claims. Auditor objections are also scanned for incorrect
claims about secret-key secrecy and pseudorandomness challenge proofs;
flags do not silently remove the objection.
