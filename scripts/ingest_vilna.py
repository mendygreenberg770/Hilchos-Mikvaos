#!/usr/bin/env python3
"""Ingest the Vilna-layout Mishnayos extraction (mishna + on-daf meforshim).

Replaces the Hebrew text of exactly the mishnayos present in the extraction
(preserving any English from Sefaria) and (re)loads the meforshim:
Rash MiShantz, Pirush HaMishnayos LehaRambam, Pirush HaRosh, Ein Mishpat,
Hagahos VeYalkutim. Run AFTER scripts/ingest_sefaria.py (re-running the
Sefaria mishnah work later would overwrite these mishna texts — just re-run
this script afterwards if you do).

Usage:
  python scripts/ingest_vilna.py
  python scripts/ingest_vilna.py --records path/to/records.jsonl --db data/x.db
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.vilna import ingest_vilna  # noqa: E402

DEFAULT_RECORDS = ROOT / "sources" / "mishnayos_vilna_taharos" / "records.jsonl"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--records", default=str(DEFAULT_RECORDS))
    p.add_argument("--db", default=None)
    args = p.parse_args()
    ingest_vilna(args.records, db_path=args.db)


if __name__ == "__main__":
    main()
