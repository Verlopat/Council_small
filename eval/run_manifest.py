"""Bind local experiment results to a specific code revision and inputs.

No provider calls. A mismatched manifest prevents old and new benchmark
data from being silently pooled after changes to Council code/config/tasks.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def _sha256(path:Path)->str:
    value=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            value.update(block)
    return value.hexdigest()


def verify_manifest(root:Path, *,experiment:str, inputs:list[Path],
                    options:str="",revision:str|None=None)->dict:
    if experiment not in {"vrf","phase_a"}:
        raise ValueError("Unknown experiment")
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    if revision is None:
        try:
            revision=subprocess.check_output(
                ["git","rev-parse","HEAD"],text=True,
                stderr=subprocess.DEVNULL).strip()
        except (OSError,subprocess.CalledProcessError) as exc:
            raise ValueError("Experiment must run from a Git working tree") from exc
    if not len(revision)==40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Invalid Git revision")
    hashes={}
    for path in inputs:
        path=Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        hashes[str(path.resolve())]=_sha256(path)
    expected={"experiment":experiment,"revision":revision,
              "inputs":hashes,"options":options}
    path=root/"experiment_manifest.json"
    if path.exists():
        try:
            present=json.loads(path.read_text(encoding="utf-8"))
        except (ValueError,UnicodeError) as exc:
            raise ValueError("Invalid experiment manifest") from exc
        if present!=expected:
            raise ValueError(
                "Benchmark code, inputs or options changed. "
                "Use a NEW RUN_DIR; do not mix previous runs.")
        return expected
    if any(root.glob("quick_*.json")) or any(root.glob("full_*.json")) or (
        any(root.glob("quick_*/results.jsonl")) or
        any(root.glob("full_*/results.jsonl"))):
        raise ValueError(
            "Existing run data has no manifest; choose a fresh RUN_DIR")
    # Exclusive creation prevents silently replacing a concurrent manifest.
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),
                   "w",encoding="utf-8") as stream:
        json.dump(expected,stream,indent=2)
        stream.write("\n")
    return expected


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--experiment",choices=("vrf","phase_a"),required=True)
    parser.add_argument("--input",action="append",type=Path,required=True)
    parser.add_argument("--options",default="")
    args=parser.parse_args(argv)
    try:
        result=verify_manifest(
            args.root,experiment=args.experiment,
            inputs=args.input,options=args.options)
    except (ValueError,OSError) as exc:
        parser.error(str(exc))
    print("Benchmark manifest verified: "+result["revision"][:12])


if __name__=="__main__":
    main()
