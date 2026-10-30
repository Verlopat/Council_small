"""Explicitly index the complete official RFC 9381 on the user's machine.

Keeps RFC copyright and legal notices with the local source. The SQLite index
is ignored by git. Indexing a document does not verify semantic entailment.
"""
from __future__ import annotations
import argparse
import re
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
    # RFC Editor plain-text layouts may pad page headers and put the number
    # in 'Request for Comments: 9381' instead of a literal 'RFC 9381'.
    # Treat line breaks / repeated whitespace as presentation only. Check
    # enough independent document features to detect an accidental wrong RFC.
    normalized = " ".join(content.split())
    checks = {
        "RFC number 9381 (Request for Comments or RFC)": bool(re.search(
            r"(?:\bRequest\s+for\s+Comments\s*:\s*9381\b|\bRFC\s+9381\b)",
            content, flags=re.IGNORECASE)),
        "VRF document title": "Verifiable Random Functions (VRFs)" in normalized,
        "section 3: VRF Security Properties": bool(re.search(
            r"\b3\.\s+VRF\s+Security\s+Properties\b",
            normalized, flags=re.IGNORECASE)),
        "section 3.1: Full Uniqueness": bool(re.search(
            r"\b3\.1\.\s+Full\s+Uniqueness\b",
            normalized, flags=re.IGNORECASE)),
        "section 3.3: Trusted Uniqueness": bool(re.search(
            r"\b3\.3\.\s+Trusted\s+Uniqueness\b",
            normalized, flags=re.IGNORECASE)),
        "section 3.4: Pseudorandomness": bool(re.search(
            r"\b3\.4\.\s+Full\s+Pseudorandomness\b",
            normalized, flags=re.IGNORECASE)),
        "IETF Trust copyright notice": "Copyright (c) 2023 IETF Trust" in normalized,
    }
    missing = [name for name, present in checks.items() if not present]
    if missing:
        p.error("RFC 9381 source validation failed; missing marker(s): " +
                "; ".join(missing))
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
