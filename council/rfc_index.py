"""Explicitly index the complete official RFC 9381 on the user's machine.

Keeps RFC copyright and legal notices with the local source. The SQLite index
is ignored by git. Indexing a document does not verify semantic entailment.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from council.verify.source import PaperIndex

URL = "https://www.rfc-editor.org/rfc/rfc9381.txt"
MAX_BYTES = 800_000


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=Path("runs/papers.sqlite3"))
    p.add_argument("--text-file", type=Path, default=None,
                   help="Offline alternative: complete official RFC text")
    args = p.parse_args(argv)
    if args.text_file is not None:
        data = args.text_file.read_bytes()
    else:
        # One explicit network request, only to the official RFC Editor.
        with urlopen(Request(URL, headers={"User-Agent": "Council-RFC-indexer/1.0"}),
                     timeout=20) as response:
            data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        p.error("RFC file exceeds conservative size limit")
    content = data.decode("utf-8-sig")
    if not all(marker in content for marker in (
            "RFC 9381", "VRF Security Properties", "Full Uniqueness",
            "Trusted Uniqueness", "Full Pseudorandomness")):
        p.error("Source does not appear to be complete RFC 9381 text")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with_index = PaperIndex(args.db)
    try:
        digest = with_index.add(
            "rfc9381", "RFC 9381: Verifiable Random Functions (VRFs)",
            content, license="IETF Trust / RFC 9381 full copyright notices",
            source_uri=URL)
    finally:
        with_index.close()
    print("Indexed official RFC 9381 locally: " + str(args.db))
    print("SHA-256: " + digest)
    print("Quote/heading lookup is provenance only, NOT security proof")


if __name__ == "__main__":
    main()
