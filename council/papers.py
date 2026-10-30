"""Index a locally owned/licensed plain-text paper for scoped quote checks.

No network calls, no claims of truth or novelty, and no remote scraping.
Usage: python -m council.papers --db runs/papers.sqlite3 --id paper-1
       --title 'Paper' --license CC-BY-4.0 --text-file paper.txt
"""
from __future__ import annotations
import argparse
from pathlib import Path
from council.verify.source import PaperIndex

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,default=Path("runs/papers.sqlite3"))
    p.add_argument("--id",required=True)
    p.add_argument("--title",required=True)
    p.add_argument("--license",required=True)
    p.add_argument("--source-uri",default="")
    p.add_argument("--text-file",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.text_file.is_file():
        p.error("Text source does not exist")
    if args.db.exists() and not args.db.is_file():
        p.error("Index is not a regular file")
    content=args.text_file.read_text(encoding="utf-8")
    if not content.strip():
        p.error("Text source is empty")
    args.db.parent.mkdir(parents=True,exist_ok=True)
    db=PaperIndex(args.db)
    try:
        digest=db.add(args.id,args.title,content,license=args.license,
                      source_uri=args.source_uri)
    finally:
        db.close()
    print("Indexed "+args.id+" sha256="+digest)
    print("Note: quote location does not establish truth or semantic entailment.")

if __name__=="__main__":
    main()
