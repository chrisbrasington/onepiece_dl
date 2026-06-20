#!/usr/bin/env python3
"""Backfill CBZ files for chapters that have a PDF but no CBZ yet.

New downloads get a CBZ automatically, but chapters fetched before that existed
only have a PDF. This walks the storage, finds every chapter with a PDF and no
CBZ, and rebuilds the CBZ from the PDF (same logic as the webapp's "Make CBZ"
button). Safe to re-run — existing CBZ files are left alone.

Usage (from the repo root):
    python scripts/backfill_cbz.py                 # scan ./data (or $ONEPIECE_STORAGE)
    python scripts/backfill_cbz.py --storage ./data
    python scripts/backfill_cbz.py --dry-run       # just list what's missing

Needs PyMuPDF (it's in the webapp's requirements):
    pip install PyMuPDF
"""

import argparse
import os
import sys

# Make `onepiece` importable when run straight from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from onepiece.storage import Storage
from onepiece.cbz import pdf_to_cbz


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--storage", default=os.environ.get("ONEPIECE_STORAGE", "data"),
                        help="storage root to scan (default: $ONEPIECE_STORAGE or ./data)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list chapters missing a CBZ without building anything")
    args = parser.parse_args(argv)

    storage = Storage(root=args.storage)
    missing = [ch for ch in storage.list_chapters() if not storage.has_cbz(ch)]

    if not missing:
        print(f"All {len(storage.list_chapters())} chapters already have a CBZ. Nothing to do.")
        return 0

    print(f"{len(missing)} chapter(s) have a PDF but no CBZ: "
          f"{', '.join(str(c) for c in missing)}")
    if args.dry_run:
        print("(dry run — nothing built)")
        return 0

    built = failed = 0
    for ch in missing:
        try:
            pdf_to_cbz(storage.pdf_path(ch), storage.cbz_path(ch))
            built += 1
        except Exception as e:
            print(f"[error] chapter {ch}: {e}")
            failed += 1

    print(f"done: {built} built, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
