#!/usr/bin/env bash
# Two quick + two full Phase-A replicates; no automatic baseline API calls.
set -euo pipefail
RUN_DIR="${RUN_DIR:-runs/phase_a_verify}"
COUNT="${COUNT:-2}"
MAX_TASKS="${MAX_TASKS:-3}"
PAUSE_SECONDS="${PAUSE_SECONDS:-90}"
TASK_FILE="${TASK_FILE:-eval/tasks/phase_a_dev.jsonl}"

if [[ ! "$COUNT" =~ ^[1-9][0-9]*$ ]] || (( COUNT > 20 )); then
  echo "COUNT must be 1..20" >&2
  exit 2
fi
if [[ ! "$MAX_TASKS" =~ ^[1-9][0-9]*$ ]] || (( MAX_TASKS > 90 )); then
  echo "MAX_TASKS must be 1..90" >&2
  exit 2
fi
if ! [[ "$PAUSE_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "PAUSE_SECONDS must be an integer number of seconds" >&2
  exit 2
fi
if [[ ! -f "$TASK_FILE" ]]; then
  echo "Missing task file: $TASK_FILE" >&2
  exit 2
fi

mkdir -p "$RUN_DIR"
python -m council.preflight --json > "$RUN_DIR/preflight.json"
python - "$RUN_DIR/preflight.json" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
required=("execution","network_isolation","host_home_isolation",
          "environment_isolation")
missing=[item for item in required if data.get(item,{}).get("status")!="pass"]
if missing:
    raise SystemExit("Unsafe sandbox: "+", ".join(missing)+
                     ". No model calls started. Inspect "+sys.argv[1])
PY

previous_call=0
for ((i=1; i<=COUNT; ++i)); do
  for mode in quick full; do
    out="$RUN_DIR/${mode}_${i}"
    result="$out/results.jsonl"
    if [[ -e "$result" ]]; then
      # Never mix partial and completed evaluations.
      if python - "$result" "$MAX_TASKS" "$mode" <<'PY'
import json,sys
path,n,mode=sys.argv[1],int(sys.argv[2]),sys.argv[3]
with open(path,encoding="utf-8") as src:
    rows=[json.loads(line) for line in src if line.strip()]
rows=[row for row in rows if row.get("system")=="council"]
if len(rows)!=n or len(set(row.get("task_id") for row in rows))!=n:
    raise SystemExit(1)
if any(row.get("mode")!=mode for row in rows):
    raise SystemExit(1)
PY
      then
        echo "Preserving completed $result"
        continue
      fi
      echo "Incomplete/invalid result: $result; move it aside before retrying" >&2
      exit 1
    fi
    if (( previous_call == 1 && PAUSE_SECONDS > 0 )); then
      echo "Pacing $PAUSE_SECONDS seconds between API-backed runs"
      sleep "$PAUSE_SECONDS"
    fi
    previous_call=1
    deadline=240
    [[ "$mode" == "full" ]] && deadline=1200
    mkdir -p "$out"
    echo "Running $mode repeat $i/$COUNT with $MAX_TASKS tasks"
    python -m eval.execute --tasks "$TASK_FILE" \
      --mode "$mode" --max-tasks "$MAX_TASKS" \
      --deadline "$deadline" --no-baselines \
      --out "$out" --confirm-free \
      2>&1 | tee "$out/console.log"
  done
done

python -m eval.compare_repeated_modes --root "$RUN_DIR" --count "$COUNT"
