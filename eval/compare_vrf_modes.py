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
from pathlib import Path

GAMES=("full_uniqueness","trusted_uniqueness","pseudorandomness")
FIELDS=("mode","run","game","correctness","notes")


def load_runs(folder: Path, count: int) -> list[dict]:
    rows=[]
    for mode in ("quick","full"):
        for index in range(1,count+1):
            path=folder/f"{mode}_{index}.json"
            if not path.is_file():
                rows.append({"mode":mode,"run":index,"found":False,
                             "status":"missing","calls":0,"proposals":0,
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
    print("Mode     Runs  Proposals  Model calls  Advisory picks  Human game ratings")
    for mode in ("quick","full"):
        entries=[r for r in runs if r["mode"]==mode and r["found"]]
        n=len(entries)
        calls=sum(x["calls"] for x in entries)
        props=sum(x["proposals"] for x in entries)
        picks=sum(bool(value) for x in entries for value in x["selected"].values())
        marks=[scores[(mode,x["run"],game)]
               for x in entries for game in GAMES
               if (mode,x["run"],game) in scores]
        grade=f"{sum(marks)/len(marks):.2f} ({len(marks)} rated)" if marks else "not rated"
        print(f"{mode:<8} {n:>4} {props:>10} {calls:>12} {picks:>14}  {grade}")
    print("\nAdvisory picks measure model selection, NOT security-game correctness.")
    print("Human game correctness is shown only for nonblank manual annotations.")
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
