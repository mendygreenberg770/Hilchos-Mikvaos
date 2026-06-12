"""FastAPI app: ask endpoint, question log, source browser, export, static UI."""

import html
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, retrieval
from .answer import answer_question
from .tagging import tag_question

app = FastAPI(title="Hilchos Mikvaos Research")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@contextmanager
def get_conn():
    conn = db.connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Ask
# --------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    strong: bool = False          # use the stronger model for difficult sugyos
    model: str | None = None      # explicit override


class TagsUpdate(BaseModel):
    topics: list[str] | None = None
    refs: list[dict] | None = None  # [{"siman": 201, "seif": 5|null}]


def _question_record(conn, qid: int) -> dict:
    row = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        raise HTTPException(404, "question not found")
    rec = dict(row)
    rec["sources_used"] = json.loads(rec["sources_used"] or "[]")
    rec["refs"] = [dict(r) for r in conn.execute(
        "SELECT siman, seif FROM question_refs WHERE question_id=? ORDER BY siman, seif",
        (qid,))]
    rec["topics"] = [r["topic"] for r in conn.execute(
        "SELECT topic FROM question_topics WHERE question_id=? ORDER BY topic", (qid,))]
    return rec


def _save_tags(conn, qid: int, refs: list[dict], topics: list[str]):
    conn.execute("DELETE FROM question_refs WHERE question_id=?", (qid,))
    conn.execute("DELETE FROM question_topics WHERE question_id=?", (qid,))
    for r in refs:
        conn.execute(
            "INSERT OR IGNORE INTO question_refs (question_id, siman, seif) VALUES (?,?,?)",
            (qid, r["siman"], r.get("seif")))
    for t in topics:
        conn.execute(
            "INSERT OR IGNORE INTO question_topics (question_id, topic) VALUES (?,?)",
            (qid, t))


@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "empty question")

    with get_conn() as conn:
        n_texts = conn.execute("SELECT count(*) c FROM texts").fetchone()["c"]
        if n_texts == 0:
            raise HTTPException(
                409, "The library is empty. Run scripts/ingest_sefaria.py first.")

        rows, detected = retrieval.retrieve(conn, question)
        model = req.model or (config.STRONG_MODEL if req.strong else config.ANSWER_MODEL)
        answer_text, model_used = answer_question(question, rows, model=model)

        cur = conn.execute(
            "INSERT INTO questions (question, answer, model, sources_used) VALUES (?,?,?,?)",
            (question, answer_text, model_used,
             json.dumps([r["ref"] for r in rows], ensure_ascii=False)))
        qid = cur.lastrowid

        tags = tag_question(question, answer_text)
        # detected refs from the question itself supplement the model's tags
        for ref in detected:
            if ref.kind == "sa" and ref.siman:
                tags["refs"].append({"siman": ref.siman, "seif": ref.seif})
        seen = set()
        uniq_refs = []
        for r in tags["refs"]:
            key = (r["siman"], r.get("seif"))
            if key not in seen:
                seen.add(key)
                uniq_refs.append(r)
        _save_tags(conn, qid, uniq_refs, tags["topics"])
        conn.commit()

        rec = _question_record(conn, qid)
        rec["sources"] = [
            {"ref": r["ref"], "sefer": r["sefer"], "text_he": r["text_he"],
             "text_en": r.get("text_en")}
            for r in rows
        ]
        return rec


# --------------------------------------------------------------------------
# Question log
# --------------------------------------------------------------------------

@app.get("/api/questions")
def list_questions(
    siman: int | None = None,
    seif: int | None = None,
    topic: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    sql = "SELECT DISTINCT qs.id FROM questions qs"
    where, params = [], []
    if siman is not None:
        sql += " JOIN question_refs qr ON qr.question_id = qs.id"
        where.append("qr.siman = ?")
        params.append(siman)
        if seif is not None:
            where.append("qr.seif = ?")
            params.append(seif)
    if topic:
        sql += " JOIN question_topics qt ON qt.question_id = qs.id"
        where.append("qt.topic = ?")
        params.append(topic.lower())
    if q:
        sql += " JOIN questions_fts f ON f.rowid = qs.id"
        where.append("questions_fts MATCH ?")
        tokens = [t for t in q.split() if t]
        params.append(" OR ".join(f'"{t}"' for t in tokens))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY qs.id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute(sql, params)]
        return [_question_record(conn, i) for i in ids]


@app.get("/api/questions/{qid}")
def get_question(qid: int):
    with get_conn() as conn:
        return _question_record(conn, qid)


@app.patch("/api/questions/{qid}/tags")
def update_tags(qid: int, body: TagsUpdate):
    with get_conn() as conn:
        rec = _question_record(conn, qid)
        refs = body.refs if body.refs is not None else rec["refs"]
        topics = ([t.strip().lower() for t in body.topics if t.strip()]
                  if body.topics is not None else rec["topics"])
        _save_tags(conn, qid, refs, topics)
        conn.commit()
        return _question_record(conn, qid)


@app.delete("/api/questions/{qid}")
def delete_question(qid: int):
    with get_conn() as conn:
        _question_record(conn, qid)  # 404 if missing
        conn.execute("DELETE FROM questions WHERE id=?", (qid,))
        return {"deleted": qid}


@app.get("/api/topics")
def list_topics():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT topic, count(*) AS n FROM question_topics GROUP BY topic ORDER BY n DESC, topic")]


@app.get("/api/simanim")
def simanim_tree():
    """Tree of siman -> seif with question counts, for the browse view."""
    with get_conn() as conn:
        tree: dict[int, dict] = {}
        for r in conn.execute(
            "SELECT siman, seif, count(*) AS n FROM question_refs GROUP BY siman, seif"
        ):
            node = tree.setdefault(r["siman"], {"siman": r["siman"], "total": 0, "seifim": {}})
            node["total"] += r["n"]
            if r["seif"] is not None:
                node["seifim"][r["seif"]] = node["seifim"].get(r["seif"], 0) + r["n"]
        out = []
        for siman in sorted(tree):
            node = tree[siman]
            node["seifim"] = [{"seif": s, "n": n} for s, n in sorted(node["seifim"].items())]
            out.append(node)
        return out


# --------------------------------------------------------------------------
# Source browser
# --------------------------------------------------------------------------

@app.get("/api/texts")
def browse_texts(
    ref: str | None = None,
    siman: int | None = None,
    seif: int | None = None,
    sefer: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    with get_conn() as conn:
        if q:
            rows = retrieval.fts_search(conn, q, limit=limit)
            return [{k: r[k] for k in ("id", "sefer", "category", "ref", "siman",
                                       "seif", "text_he", "text_en")} for r in rows]
        where, params = [], []
        if ref:
            where.append("ref LIKE ?")
            params.append(f"%{ref}%")
        if siman is not None:
            where.append("siman = ?")
            params.append(siman)
        if seif is not None:
            where.append("seif = ?")
            params.append(seif)
        if sefer:
            where.append("sefer = ?")
            params.append(sefer)
        sql = ("SELECT id, sefer, category, ref, siman, seif, text_he, text_en "
               "FROM texts")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY siman, seif, ref LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in conn.execute(sql, params)]


@app.get("/api/sefarim")
def list_sefarim():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT sefer, category, count(*) AS n FROM texts GROUP BY sefer, category ORDER BY sefer")]


# --------------------------------------------------------------------------
# Account connection + one-click library loading
# --------------------------------------------------------------------------

class ConnectRequest(BaseModel):
    api_key: str


def _save_env_var(key: str, value: str):
    env_path = config.BASE_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    lines = [l for l in lines if not l.strip().startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


@app.post("/api/connect")
def connect_account(req: ConnectRequest):
    """Paste-an-API-key connection from the UI: validate, persist to .env,
    activate immediately (no restart)."""
    key = req.api_key.strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(400, "זה לא נראה כמו מפתח API של Anthropic (אמור להתחיל ב-sk-ant-)")
    import anthropic
    try:
        anthropic.Anthropic(api_key=key).models.list()
    except anthropic.AuthenticationError:
        raise HTTPException(400, "המפתח לא התקבל — ודא שהועתק במלואו ושהוא פעיל")
    except anthropic.APIError as e:
        raise HTTPException(502, f"לא ניתן לאמת את המפתח מול השרת: {e.message}")
    _save_env_var("ANTHROPIC_API_KEY", key)
    os.environ["ANTHROPIC_API_KEY"] = key
    return health()


_ingest_state = {"running": False, "done": False, "error": None, "log": []}


def _run_ingestion():
    st = _ingest_state
    try:
        from ingest.sefaria import ingest_work
        from ingest.vilna import ingest_vilna
        from ingest.works import WORKS

        conn = db.connect()
        for work in WORKS:
            st["log"].append(f"טוען {work['sefer']} מספריא…")
            try:
                stored, errors = ingest_work(conn, work, verbose=False)
                mark = "✓" if not errors else "⚠"
                line = f"{mark} {work['sefer']}: {stored} קטעים"
                if errors:
                    line += f" ({len(errors)} שגיאות — ראה לוג שרת)"
                    for e in errors:
                        print(f"ingest error: {e}")
                st["log"][-1] = line
            except Exception as e:
                st["log"][-1] = f"✗ {work['sefer']}: {e}"
        conn.close()

        # Vilna extraction last, so its mishna text wins over Sefaria's
        records = config.BASE_DIR / "sources" / "mishnayos_vilna_taharos" / "records.jsonl"
        if records.exists():
            st["log"].append("טוען משניות (וילנא) + ר\"ש, פיה\"מ, רא\"ש, הגהות…")
            ingest_vilna(records, verbose=False)
            st["log"][-1] = "✓ משניות דפוס וילנא + מפרשים שעל הדף"
        st["log"].append("הטעינה הסתיימה.")
    except Exception as e:
        st["error"] = str(e)
    finally:
        st["running"] = False
        st["done"] = True


@app.post("/api/ingest")
def start_ingest():
    if _ingest_state["running"]:
        raise HTTPException(409, "טעינה כבר רצה")
    _ingest_state.update(running=True, done=False, error=None, log=[])
    threading.Thread(target=_run_ingestion, daemon=True).start()
    return {"started": True}


@app.get("/api/ingest/status")
def ingest_status():
    return _ingest_state


@app.get("/api/catalog")
def catalog():
    """Every sefer the system is built to hold — loaded or not — with counts.
    Lets the UI show the full seforim list even before ingestion."""
    from ingest.vilna import COMMENTARIES, MARGINALIA
    from ingest.works import WORKS

    planned: list[tuple[str, str]] = []
    seen = set()
    for w in WORKS:
        if w["sefer"] not in seen:
            seen.add(w["sefer"])
            planned.append((w["sefer"], w["category"]))
    for meta in list(COMMENTARIES.values()) + list(MARGINALIA.values()):
        if meta["sefer"] not in seen:
            seen.add(meta["sefer"])
            planned.append((meta["sefer"], meta["category"]))

    with get_conn() as conn:
        counts = {r["sefer"]: r["n"] for r in conn.execute(
            "SELECT sefer, count(*) n FROM texts GROUP BY sefer")}
    out = [{"sefer": s, "category": c, "loaded": counts.pop(s, 0)}
           for s, c in planned]
    # anything in the DB that isn't in the configured catalog (custom additions)
    for sefer, n in counts.items():
        with get_conn() as conn:
            cat = conn.execute("SELECT category FROM texts WHERE sefer=? LIMIT 1",
                               (sefer,)).fetchone()["category"]
        out.append({"sefer": sefer, "category": cat, "loaded": n})
    return out


@app.get("/api/health")
def health():
    """Setup status for the UI: how Claude is connected, is the library loaded."""
    from . import llm
    with get_conn() as conn:
        return {
            "claude_mode": llm.mode(),  # "api" | "subscription" | "none"
            "embeddings_enabled": bool(config.VOYAGE_API_KEY),
            "texts": conn.execute("SELECT count(*) c FROM texts").fetchone()["c"],
            "answer_model": config.ANSWER_MODEL,
            "strong_model": config.STRONG_MODEL,
        }


@app.get("/api/stats")
def stats():
    with get_conn() as conn:
        return {
            "texts": conn.execute("SELECT count(*) c FROM texts").fetchone()["c"],
            "embedded": conn.execute(
                "SELECT count(*) c FROM texts WHERE embedding IS NOT NULL").fetchone()["c"],
            "questions": conn.execute("SELECT count(*) c FROM questions").fetchone()["c"],
        }


# --------------------------------------------------------------------------
# Export (printable HTML → print to PDF, or markdown)
# --------------------------------------------------------------------------

@app.get("/api/export")
def export(siman: int | None = None, topic: str | None = None,
           fmt: str = Query("html", pattern="^(html|md)$")):
    items = list_questions(siman=siman, topic=topic, q=None, seif=None,
                           limit=200, offset=0)
    title_bits = []
    if siman:
        title_bits.append(f"סימן {siman}")
    if topic:
        title_bits.append(topic)
    title = "הלכות מקוואות — " + (", ".join(title_bits) or "כל השאלות")

    if fmt == "md":
        lines = [f"# {title}", ""]
        for it in items:
            lines += [f"## {it['question']}", "",
                      f"*{it['ts']}* — תגיות: {', '.join(it['topics']) or '—'}", "",
                      it["answer"], "",
                      "**מקורות:** " + "; ".join(it["sources_used"]), "", "---", ""]
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")

    body = []
    for it in items:
        srcs = "; ".join(html.escape(s) for s in it["sources_used"])
        topics = ", ".join(html.escape(t) for t in it["topics"]) or "—"
        body.append(f"""
        <article>
          <h2>{html.escape(it['question'])}</h2>
          <p class="meta">{html.escape(it['ts'])} · תגיות: {topics}</p>
          <div class="answer">{html.escape(it['answer']).replace(chr(10), '<br>')}</div>
          <p class="sources">מקורות: {srcs}</p>
        </article>""")
    doc = f"""<!doctype html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body {{ font-family: 'Frank Ruhl Libre', 'Times New Roman', serif; max-width: 50rem;
        margin: 2rem auto; padding: 0 1rem; line-height: 1.7; font-size: 1.05rem; }}
 h1 {{ border-bottom: 2px solid #333; padding-bottom: .5rem; }}
 article {{ page-break-inside: avoid; border-bottom: 1px solid #ccc; padding: 1rem 0; }}
 .meta, .sources {{ color: #666; font-size: .85rem; }}
 @media print {{ body {{ margin: 0; }} }}
</style></head><body><h1>{html.escape(title)}</h1>{''.join(body)}</body></html>"""
    return HTMLResponse(doc)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
