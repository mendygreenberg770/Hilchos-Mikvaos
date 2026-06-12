#!/usr/bin/env python3
"""Ingest the configured Sefaria works into SQLite.

Usage:
  python scripts/ingest_sefaria.py                 # everything in ingest/works.py
  python scripts/ingest_sefaria.py --works sa,shach,taz
  python scripts/ingest_sefaria.py --db data/test.db
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.sefaria import ingest  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--works", help="comma-separated work keys (default: all)")
    p.add_argument("--db", help="database path (default: data/mikvaos.db)")
    args = p.parse_args()
    keys = [k.strip() for k in args.works.split(",")] if args.works else None
    ingest(work_keys=keys, db_path=args.db)


if __name__ == "__main__":
    main()
