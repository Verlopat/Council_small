"""Task loading enforces split separation and licensing."""
import json
from pathlib import Path
KINDS={"numeric","code","symbolic","security","research","literature"}
def load(path,split="dev"):
    if split not in {"dev","heldout"}:raise ValueError("Invalid split")
    out=[];ids=set()
    for line in Path(path).read_text().splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if row.get("split")!=split:continue
        if not row.get("id") or row["id"] in ids or row.get("kind") not in KINDS or not row.get("prompt") or not row.get("license"):
            raise ValueError("Task missing unique ID, kind, license or question")
        ids.add(row["id"]);out.append(row)
    return out
