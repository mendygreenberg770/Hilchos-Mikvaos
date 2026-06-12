#!/usr/bin/env python3
"""Retrieval test harness — run AFTER ingestion, BEFORE wiring up Claude.

Asks 10 known questions and checks that the right sources come back. This is
the main quality lever: if retrieval is bad, answers will be bad no matter the
model. Tune ingest/works.py and app/retrieval.py until this is green.

Usage: python scripts/test_retrieval.py [--db PATH] [-v]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, retrieval  # noqa: E402

# (question, [substrings — at least one must appear in a retrieved ref])
CASES = [
    # 1. explicit ref detection, English numeric
    ("What does the Shach say in 201:5?", ["Shach YD 201:5"]),
    # 2. explicit ref detection, Hebrew
    ("מה כתוב בסימן קצח סעיף א?", ["YD 198:1"]),
    # 3. bare siman
    ("Show me the sugya of siman 202", ["YD 202"]),
    # 4. gemara daf
    ("What is the gemara in Niddah 66b about?", ["Niddah 66b"]),
    # 5. mishnah ref pulls mishnah + its meforshim
    ("Mikvaos 2:3 — what is the case?", ["Mikvaos 2:3"]),
    # 6. keyword: chatzitza lives in siman 198
    ("מה הדין של חציצה בטבילה?", ["198"]),
    # 7. keyword: chafifa is siman 199
    ("דיני חפיפה קודם טבילה", ["199"]),
    # 8. keyword: sheuvin / zochalin — mikveh construction, siman 201
    ("האם מים שאובין פוסלים את המקוה?", ["201"]),
    # 9. keyword: arba'im se'ah
    ("כמה זה ארבעים סאה ומה השיעור למקוה?", ["201"]),
    # 10. tevilas keilim — siman 202 (or the gemara/mishnah equivalents)
    ("טבילת כלים שלקחו מן הגוי", ["202"]),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    conn = db.connect(args.db)
    n = conn.execute("SELECT count(*) c FROM texts").fetchone()["c"]
    if n == 0:
        raise SystemExit("Library is empty — run scripts/ingest_sefaria.py first.")
    print(f"Library: {n} chunks\n")

    passed = 0
    for i, (question, expected) in enumerate(CASES, 1):
        rows, refs = retrieval.retrieve(conn, question)
        got_refs = [r["ref"] for r in rows]
        hit = any(any(e in ref for ref in got_refs) for e in expected)
        status = "PASS" if hit else "FAIL"
        if hit:
            passed += 1
        print(f"[{status}] {i:2d}. {question}")
        if args.verbose or not hit:
            print(f"        detected refs: {[r.label() for r in refs]}")
            print(f"        expected one of: {expected}")
            for ref in got_refs[:8]:
                print(f"        - {ref}")
    print(f"\n{passed}/{len(CASES)} passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
