#!/usr/bin/env bash
# Reproducible, resumable VRF quick/full comparison. Uses LOCAL provider keys.
# Run at repository root: bash scripts/benchmark_vrf_modes.sh
set -euo pipefail

if [[ ! -f "${PAPER_INDEX:-runs/papers.sqlite3}" ]]; then
  echo "Missing paper index: ${PAPER_INDEX:-runs/papers.sqlite3}. Index RFC 9381 before benchmarking." >&2
  exit 2
fi

COUNT="${COUNT:-5}"
RUN_DIR="${RUN_DIR:-runs}"
PAPER_INDEX="${PAPER_INDEX:-runs/papers.sqlite3}"
if ! [[ "$COUNT" =~ ^[1-9][0-9]*$ ]] || (( COUNT > 100 )); then
  echo "COUNT must be an integer between 1 and 100" >&2
  exit 2
fi

QUESTION='Explain full uniqueness, trusted uniqueness, and pseudorandomness security games for a lattice-based VRF.'
# Avoid quick mode immediately consuming quota before its paired full run.
# Set PAUSE_SECONDS=0 to opt out; never overwrite completed results.
PAUSE_SECONDS="${PAUSE_SECONDS:-90}"
if ! [[ "$PAUSE_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "PAUSE_SECONDS must be an integer number of seconds" >&2
  exit 2
fi
previous_call=0
mkdir -p "$RUN_DIR"
# This command does not contact any model provider and fails closed if a
# previously observed sandbox isolation defect is still present.
python -m council.preflight --json > "$RUN_DIR/preflight.json"
python - "$RUN_DIR/preflight.json" <<'PY'
import json,sys
report=json.load(open(sys.argv[1],encoding="utf-8"))
required=("execution","network_isolation","host_home_isolation",
          "environment_isolation")
bad=[k for k in required if report.get(k,{}).get("status")!="pass"]
if bad:
    raise SystemExit("Sandbox isolation failed: "+", ".join(bad)+
                     ". Inspect "+sys.argv[1]+". No provider calls started.")
PY
echo "Results directory: $RUN_DIR"

for ((i=1; i<=COUNT; ++i)); do
  for mode in quick full; do
    target="$RUN_DIR/${mode}_${i}.json"
    if [[ -f "$target" ]]; then
      if python -m json.tool "$target" > /dev/null 2>&1; then
        echo "Preserving existing $target"
        continue
      fi
      echo "Existing $target is invalid JSON; move it aside before retrying." >&2
      exit 1
    fi
    if (( previous_call == 1 && PAUSE_SECONDS > 0 )); then
      echo "Pacing: sleeping ${PAUSE_SECONDS}s between live API runs"
      sleep "$PAUSE_SECONDS"
    fi
    previous_call=1
    tmp="${target}.partial"
    deadline=240
    [[ "$mode" == "full" ]] && deadline=1200
    # Use the same council.yaml endpoint allowances for both modes.
    # Explicit --timeout 60 is a strict ceiling, which can truncate
    # Command/Nemotron and unfairly penalize full mode.
    echo "Running $mode sample $i/$COUNT (provider quotas and deadlines apply)"
    if ! python -m council.cli \
        --mode "$mode" --deadline "$deadline" \
        --paper-index "$PAPER_INDEX" --run-dir "$RUN_DIR" \
        --json "$QUESTION" \
        > "$tmp" 2> "$RUN_DIR/${mode}_${i}.stderr.log"; then
      echo "Run failed; inspect $tmp and $RUN_DIR/${mode}_${i}.stderr.log" >&2
      exit 1
    fi
    if ! python -m json.tool "$tmp" > /dev/null; then
      echo "Invalid JSON output for $mode sample $i; preserved $tmp" >&2
      exit 1
    fi
    mv "$tmp" "$target"
  done
done

python -m eval.compare_vrf_modes --input-dir "$RUN_DIR" --count "$COUNT" \
  --scores "$RUN_DIR/vrf_human_scores.csv"
echo "Fill the correctness column in $RUN_DIR/vrf_human_scores.csv, then rerun"
echo "python -m eval.compare_vrf_modes --input-dir $RUN_DIR --count $COUNT --scores $RUN_DIR/vrf_human_scores.csv"
