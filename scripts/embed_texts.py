#!/usr/bin/env python3
"""Embed library texts that don't yet have an embedding (Voyage AI).

Requires VOYAGE_API_KEY. Safe to re-run; only fills NULL embeddings.

Usage: python scripts/embed_texts.py [--db PATH] [--batch 64]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, embeddings  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=None)
    p.add_argument("--batch", type=int, default=64)
    args = p.parse_args()

    if not embeddings.enabled():
        raise SystemExit("VOYAGE_API_KEY is not set — nothing to do.")

    conn = db.connect(args.db)
    rows = conn.execute(
        "SELECT id, text_he_plain FROM texts WHERE embedding IS NULL ORDER BY id"
    ).fetchall()
    print(f"{len(rows)} texts to embed")

    for i in range(0, len(rows), args.batch):
        batch = rows[i:i + args.batch]
        vecs = embeddings.embed([r["text_he_plain"][:8000] for r in batch],
                                input_type="document")
        for row, vec in zip(batch, vecs):
            conn.execute("UPDATE texts SET embedding=? WHERE id=?",
                         (embeddings.to_blob(vec), row["id"]))
        conn.commit()
        print(f"  embedded {min(i + args.batch, len(rows))}/{len(rows)}")
    conn.close()


if __name__ == "__main__":
    main()
