# Hilchos Mikvaos Research System

A personal Torah research tool: a searchable library of seforim on hilchos
mikvaos with a Claude-powered Q&A interface. Every question is answered from
the actual texts (RAG) and automatically logged, tagged by siman/seif and topic.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in ANTHROPIC_API_KEY (and optionally VOYAGE_API_KEY)
```

Environment variables can be set in the shell or via `.env` + your own loader
(e.g. `set -a; source .env; set +a`).

## 1. Build the library (Sefaria ingestion)

```bash
python scripts/ingest_sefaria.py                  # all works in ingest/works.py
python scripts/ingest_sefaria.py --works sa,shach # or a subset
```

Ingests into `data/mikvaos.db`: Shulchan Aruch YD 198–202 with Shach, Taz,
Be'er Heitev, and Pischei Teshuva; Mishnayos Mikvaos with Bartenura and Tosfos
Yom Tov; Rambam Hilchos Mikvaos; the relevant gemaras (Niddah 66–67,
Chagigah 18b–19a) with Rashi/Tosfos; and the Rosh's Hilchos Mikvaos.

Re-runs are safe (rows are upserted by ref). If a work fails, it is almost
always a Sefaria index-title mismatch — the summary prints exactly which title
failed; fix it in `ingest/works.py` and re-run just that work.

> **Note for Claude Code on the web:** the ingestion script needs network
> access to `www.sefaria.org` — add it to the environment's network allowlist.

## 2. Verify retrieval (do this before trusting any answers)

```bash
python scripts/test_retrieval.py -v
```

Runs 10 known questions and checks the right sources come back. This is the
main quality lever — if retrieval is bad, answers will be bad no matter the
model. Offline unit tests (no network/API keys needed):

```bash
python -m unittest discover tests -v
```

## 3. (Optional) Embeddings for semantic search

Reference detection + FTS5 keyword search work without this. To add semantic
search, set `VOYAGE_API_KEY` and run:

```bash
python scripts/embed_texts.py
```

## 4. Run the app

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
```

Open http://localhost:8000 — Hebrew RTL UI with three views:

- **שאלה** — ask a question; sources are retrieved, Claude answers with exact
  citations, and the Q&A is auto-tagged and logged. The "סוגיא קשה" toggle
  switches to the stronger model for difficult sugyos.
- **יומן** — browse the question log by siman, topic, or full-text search;
  edit tags; export a siman/topic's worth of Q&A to printable HTML (→ PDF via
  the browser) or Markdown — useful for building a personal kuntres over time.
- **מקורות** — browse/search the library itself.

## How retrieval works (hybrid)

1. **Reference detection** — if the question names a siman/seif ("the Shach in
   201:5", "סימן קצח סעיף א", "רא:ה"), a daf ("Niddah 66b", "נדה סו:"), or a
   mishnah ("Mikvaos 2:3"), those rows are pulled directly and always included.
2. **Keyword/BM25** — SQLite FTS5 over nikud-stripped Hebrew + English, for
   technical terms (חציצה, זוחלין, שאובין).
3. **Semantic search** — cosine similarity over Voyage embeddings (optional).

Results are merged, deduped, and the top ~20 chunks go to Claude with a
citation-enforcing system prompt (answer only from sources, cite exact refs,
present machlokes as machlokes, never invent a mekor, research — not psak).

## Models

| Use | Default | Override |
|---|---|---|
| Everyday answers | `claude-sonnet-4-6` | `ANSWER_MODEL` |
| Difficult sugyos (UI toggle) | `claude-opus-4-8` | `STRONG_MODEL` |
| Auto-tagging | `claude-haiku-4-5` | `TAGGING_MODEL` |

## Project layout

```
app/        config, db schema, ref parsing, retrieval, answer + tagging calls, FastAPI routes
ingest/     Sefaria works config + ingestion library
scripts/    ingest_sefaria.py, embed_texts.py, test_retrieval.py (retrieval harness)
static/     single-page RTL UI
tests/      offline unit tests (stdlib unittest)
data/       SQLite database (gitignored) — back this up; it IS the system
```

## Roadmap (per the build spec)

- [x] 1. Sefaria ingestion → SQLite with exact refs
- [x] 2. Hybrid retrieval + test harness
- [x] 3. Answer endpoint with citation-enforcing prompt
- [x] 4. Minimal chat UI (RTL from day one)
- [x] 5. Auto-tagging + question log + browse UI + export
- [ ] 6. PDF/OCR ingestion for non-Sefaria seforim (acharonim, contemporary)
- [ ] 7. Deploy for phone access (VPS/Fly.io behind a password)
