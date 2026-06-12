"""Hybrid retrieval: reference detection → direct lookup, FTS5/BM25 keywords,
and (optionally) embedding similarity. Merged, deduped, top-K to Claude."""

import re

from . import config, db, embeddings
from .refs import Ref, detect_refs

_STOPWORDS = {
    # Hebrew function words / question words
    "של", "את", "אם", "על", "מה", "מהו", "מהי", "האם", "איך", "כיצד", "למה",
    "מדוע", "יש", "אין", "לא", "כן", "זה", "זו", "הוא", "היא", "או", "גם",
    "כל", "עם", "אבל", "רק", "כי", "אז", "שם", "פה", "דין", "הדין",
    # English
    "the", "a", "an", "is", "are", "was", "were", "what", "when", "how", "why",
    "does", "do", "din", "can", "may", "be", "to", "of", "in", "on", "for",
    "and", "or", "if", "it", "this", "that", "there", "about", "with",
}

_WORD_RE = re.compile(r"[\w֐-׿\"'׳״]+")


def _fts_tokens(question: str) -> list[str]:
    plain = db.strip_nikud(question)
    tokens = []
    for w in _WORD_RE.findall(plain):
        w = w.strip("\"'׳״")
        if len(w) < 2 or w.lower() in _STOPWORDS or w.isdigit():
            continue
        tokens.append(w)
    return tokens[:20]


def lookup_refs(conn, refs: list[Ref]) -> list[dict]:
    rows: list[dict] = []
    for ref in refs:
        if ref.kind == "sa":
            if ref.seif is not None:
                cur = conn.execute(
                    "SELECT * FROM texts WHERE siman=? AND seif=? ORDER BY ref",
                    (ref.siman, ref.seif),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM texts WHERE siman=? ORDER BY seif, ref",
                    (ref.siman,),
                )
        elif ref.kind == "gemara":
            # Matches the gemara itself plus Rashi/Tosfos rows on the same daf.
            pat = f"%{ref.masechta} {ref.daf}%"
            cur = conn.execute(
                "SELECT * FROM texts WHERE ref LIKE ? ORDER BY ref", (pat,)
            )
        else:  # mishnah — matches the mishnah + everything printed on it
            pat = f"%Mikvaos {ref.chapter}:{ref.mishnah}"
            cur = conn.execute(
                "SELECT * FROM texts WHERE category IN ('mishna','rishon','acharon') "
                "AND (ref LIKE ? OR ref LIKE ? OR ref LIKE ?) ORDER BY ref",
                (pat, pat + ":%", pat + " %"),
            )
        rows.extend(dict(r) for r in cur.fetchall())
    # dedupe preserving order, cap
    seen, out = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out[: config.REF_LIMIT]


def fts_search(conn, question: str, limit: int | None = None) -> list[dict]:
    tokens = _fts_tokens(question)
    if not tokens:
        return []
    query = " OR ".join(f'"{t}"' for t in tokens)
    try:
        cur = conn.execute(
            """SELECT t.*, bm25(texts_fts) AS fts_rank
               FROM texts_fts JOIN texts t ON t.id = texts_fts.rowid
               WHERE texts_fts MATCH ? ORDER BY fts_rank LIMIT ?""",
            (query, limit or config.FTS_LIMIT),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def semantic_search(conn, question: str, limit: int | None = None) -> list[dict]:
    if not embeddings.enabled():
        return []
    try:
        import numpy as np
        qvec = np.array(embeddings.embed([question], input_type="query")[0],
                        dtype=np.float32)
        cur = conn.execute("SELECT id, embedding FROM texts WHERE embedding IS NOT NULL")
        ids, mats = [], []
        for row in cur:
            ids.append(row["id"])
            mats.append(np.frombuffer(row["embedding"], dtype=np.float32))
        if not ids:
            return []
        mat = np.stack(mats)
        sims = mat @ qvec / (np.linalg.norm(mat, axis=1) * np.linalg.norm(qvec) + 1e-9)
        order = sims.argsort()[::-1][: limit or config.EMBED_LIMIT]
        out = []
        for i in order:
            row = conn.execute("SELECT * FROM texts WHERE id=?", (ids[i],)).fetchone()
            d = dict(row)
            d["similarity"] = float(sims[i])
            out.append(d)
        return out
    except Exception:
        return []  # embeddings are best-effort; never block retrieval


def retrieve(conn, question: str, top_k: int | None = None):
    """Returns (rows, detected_refs). Rows are dicts ordered by merged score."""
    top_k = top_k or config.TOP_K
    refs = detect_refs(question)
    ref_rows = lookup_refs(conn, refs)
    fts_rows = fts_search(conn, question)
    emb_rows = semantic_search(conn, question)

    scores: dict[int, float] = {}
    by_id: dict[int, dict] = {}

    for r in ref_rows:                       # explicit citations always win
        scores[r["id"]] = scores.get(r["id"], 0) + 1000
        by_id[r["id"]] = r
    for i, r in enumerate(fts_rows):
        scores[r["id"]] = scores.get(r["id"], 0) + max(0.0, 30.0 - i)
        by_id.setdefault(r["id"], r)
    for r in emb_rows:
        scores[r["id"]] = scores.get(r["id"], 0) + r.get("similarity", 0) * 40
        by_id.setdefault(r["id"], r)

    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)
    keep = max(top_k, len(ref_rows))         # never drop directly-cited rows
    return [by_id[i] for i in ranked[:keep]], refs
