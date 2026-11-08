"""Compare VRF quick/full Council runs without claiming automatic correctness.

Run ten local API experiments as desired, then:
    python -m eval.compare_vrf_modes --input-dir runs --count 5 \
        --scores runs/vrf_human_scores.csv

The scores file is an editable annotation template. Blank grades mean
unassessed, NOT incorrect. Reference alignment opinions are never treated
as human/scientific correctness ratings.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

GAMES=("full_uniqueness","trusted_uniqueness","pseudorandomness")
FIELDS=("mode","run","game","correctness","notes")


def recorded_provider_attempts(folder: Path, run_id: object) -> int | None:
    """Count started requests + scheduled retries in a local run database.

    An attempt count includes recorded retries and provider failures, unlike
    actual_models, which reflects completed model responses. It is NOT a
    charged-token or provider-billing measurement.
    """
    if (not isinstance(run_id,str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",run_id)):
        return None
    path=folder/(run_id+".sqlite3")
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(
                "file:"+str(path.resolve())+"?mode=ro",uri=True)) as conn:
            row=conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type IN "
                "('model_call_started','model_call_retry')").fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return None


def load_runs(folder: Path, count: int) -> list[dict]:
    rows=[]
    for mode in ("quick","full"):
        for index in range(1,count+1):
            path=folder/f"{mode}_{index}.json"
            if not path.is_file():
                rows.append({"mode":mode,"run":index,"found":False,
                             "status":"missing","calls":0,"attempts":None,
                             "proposals":0,
                             "selected":{g:None for g in GAMES}})
                continue
            payload=json.loads(path.read_text(encoding="utf-8"))
            topics={str(r.get("topic")):r for r in
                    payload.get("topic_consolidation",[]) or [] if isinstance(r,dict)}
            selected={game:topics.get(game,{}).get("best_version_id")
                      for game in GAMES}
            rows.append({"mode":mode,"run":index,"found":True,
                         "status":payload.get("research_result",{}).get(
                             "completion_status","unknown"),
                         "calls":len(payload.get("actual_models") or []),
                         "attempts":recorded_provider_attempts(
                             folder,payload.get("run_id")),
                         "proposals":len(payload.get("proposals") or []),
                         "selected":selected})
    return rows


def ensure_scores(path:Path, runs:list[dict]) -> dict[tuple[str,int,str],float]:
    """Create missing annotation rows without overwriting human grades."""
    existing={}
    if path.is_file():
        with path.open(newline="",encoding="utf-8") as source:
            for item in csv.DictReader(source):
                if not all(k in item for k in FIELDS):
                    raise ValueError("Score file missing required columns")
                key=(item["mode"],int(item["run"]),item["game"])
                score=(item.get("correctness") or "").strip()
                if score:
                    value=float(score)
                    if not 0<=value<=1:
                        raise ValueError("Correctness must be between 0 and 1")
                    existing[key]=value
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("w",newline="",encoding="utf-8") as dest:
            writer=csv.DictWriter(dest,fieldnames=FIELDS)
            writer.writeheader()
            for item in runs:
                if not item["found"]:
                    continue
                for game in GAMES:
                    writer.writerow({"mode":item["mode"],"run":item["run"],
                                     "game":game,"correctness":"","notes":
                                     "0=wrong, 0.5=partially right, 1=correct; "
                                     "compare to RFC 9381"})
    return existing


def print_report(runs:list[dict],scores:dict) -> None:
    print("Mode     Runs  Proposals  Responses  Logged attempts  Advisory picks  Human game ratings")
    for mode in ("quick","full"):
        entries=[r for r in runs if r["mode"]==mode and r["found"]]
        n=len(entries)
        calls=sum(x["calls"] for x in entries)
        attempts=[x["attempts"] for x in entries if x.get("attempts") is not None]
        attempt_label=(str(sum(attempts))+
                       ("" if len(attempts)==n else
                        f" ({len(attempts)}/{n} logged)"))
        if not attempts:
            attempt_label="n/a"
        props=sum(x["proposals"] for x in entries)
        picks=sum(bool(value) for x in entries for value in x["selected"].values())
        marks=[scores[(mode,x["run"],game)]
               for x in entries for game in GAMES
               if (mode,x["run"],game) in scores]
        grade=f"{sum(marks)/len(marks):.2f} ({len(marks)} rated)" if marks else "not rated"
        print(f"{mode:<8} {n:>4} {props:>10} {calls:>10} "
              f"{attempt_label:>16} {picks:>14}  {grade}")
    print("\nAdvisory picks measure model selection, NOT security-game correctness.")
    print("Human game correctness is shown only for nonblank manual annotations.")
    print("Responses omit provider failures; logged attempts include started "
          "requests and scheduled retries but are not billable-token measurements.")
    missing=[f"{r['mode']}_{r['run']}" for r in runs if not r["found"]]
    if missing:
        print("Missing JSON files: "+", ".join(missing))


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir",type=Path,default=Path("runs"))
    parser.add_argument("--count",type=int,default=5)
    parser.add_argument("--scores",type=Path,
                        default=Path("runs/vrf_human_scores.csv"))
    options=parser.parse_args(argv)
    if not 1<=options.count<=100:
        parser.error("--count must be in 1..100")
    runs=load_runs(options.input_dir,options.count)
    scores=ensure_scores(options.scores,runs)
    print_report(runs,scores)
    print("Human annotation CSV: "+str(options.scores))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
