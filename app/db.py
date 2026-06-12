"""SQLite schema and connection helpers.

texts      — the library: one row per seif / mishnah / gemara segment / s"k.
questions  — the Q&A log, with join tables for siman/seif refs and topic tags.
FTS5 virtual tables mirror both for BM25 keyword search.
"""

import re
import sqlite3
import unicodedata
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS texts (
    id            INTEGER PRIMARY KEY,
    sefer         TEXT NOT NULL,           -- e.g. "Shach", "Mishnayos Mikvaos"
    category      TEXT NOT NULL,           -- rishon/acharon/shulchan_aruch/mishna/gemara/rambam/contemporary
    ref           TEXT NOT NULL UNIQUE,    -- canonical citation, e.g. "Shach YD 201:5:3"
    sefaria_ref   TEXT,                    -- the Sefaria tref this row came from
    siman         INTEGER,                 -- for SA-structured texts only
    seif          INTEGER,
    text_he       TEXT NOT NULL,
    text_he_plain TEXT NOT NULL,           -- nikud/HTML stripped, for FTS
    text_en       TEXT,
    embedding     BLOB                     -- float32 vector, NULL until embedded
);
CREATE INDEX IF NOT EXISTS idx_texts_siman ON texts(siman, seif);
CREATE INDEX IF NOT EXISTS idx_texts_sefer ON texts(sefer);

CREATE VIRTUAL TABLE IF NOT EXISTS texts_fts USING fts5(
    text_he_plain, text_en,
    content='texts', content_rowid='id',
    tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS texts_ai AFTER INSERT ON texts BEGIN
    INSERT INTO texts_fts(rowid, text_he_plain, text_en)
    VALUES (new.id, new.text_he_plain, new.text_en);
END;
CREATE TRIGGER IF NOT EXISTS texts_ad AFTER DELETE ON texts BEGIN
    INSERT INTO texts_fts(texts_fts, rowid, text_he_plain, text_en)
    VALUES ('delete', old.id, old.text_he_plain, old.text_en);
END;
CREATE TRIGGER IF NOT EXISTS texts_au AFTER UPDATE OF text_he_plain, text_en ON texts BEGIN
    INSERT INTO texts_fts(texts_fts, rowid, text_he_plain, text_en)
    VALUES ('delete', old.id, old.text_he_plain, old.text_en);
    INSERT INTO texts_fts(rowid, text_he_plain, text_en)
    VALUES (new.id, new.text_he_plain, new.text_en);
END;

CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL DEFAULT (datetime('now')),
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL,
    model        TEXT,
    sources_used TEXT                      -- JSON array of refs sent to Claude
);

CREATE TABLE IF NOT EXISTS question_refs (
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    siman       INTEGER NOT NULL,
    seif        INTEGER,
    UNIQUE(question_id, siman, seif)
);
CREATE INDEX IF NOT EXISTS idx_qrefs ON question_refs(siman, seif);

CREATE TABLE IF NOT EXISTS question_topics (
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    UNIQUE(question_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_qtopics ON question_topics(topic);

CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
    question, answer,
    content='questions', content_rowid='id',
    tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS questions_ai AFTER INSERT ON questions BEGIN
    INSERT INTO questions_fts(rowid, question, answer)
    VALUES (new.id, new.question, new.answer);
END;
CREATE TRIGGER IF NOT EXISTS questions_ad AFTER DELETE ON questions BEGIN
    INSERT INTO questions_fts(questions_fts, rowid, question, answer)
    VALUES ('delete', old.id, old.question, old.answer);
END;
"""

# Hebrew cantillation + vowel points (U+0591–U+05C7)
_NIKUD_RE = re.compile(r"[֑-ׇ]")
_TAG_RE = re.compile(r"<[^>]+>")


def strip_nikud(text: str) -> str:
    return _NIKUD_RE.sub("", text)


def strip_html(text: str) -> str:
    import html
    return html.unescape(_TAG_RE.sub(" ", text))


def normalize_he(text: str) -> str:
    """HTML + nikud stripped, whitespace collapsed — what goes in the FTS column."""
    text = strip_nikud(strip_html(unicodedata.normalize("NFC", text)))
    return re.sub(r"\s+", " ", text).strip()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def insert_text(conn, *, sefer, category, ref, text_he, sefaria_ref=None,
                siman=None, seif=None, text_en=None):
    conn.execute(
        """INSERT INTO texts (sefer, category, ref, sefaria_ref, siman, seif,
                              text_he, text_he_plain, text_en)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ref) DO UPDATE SET
             sefer=excluded.sefer, category=excluded.category,
             sefaria_ref=excluded.sefaria_ref, siman=excluded.siman,
             seif=excluded.seif, text_he=excluded.text_he,
             text_he_plain=excluded.text_he_plain, text_en=excluded.text_en""",
        (sefer, category, ref, sefaria_ref, siman, seif,
         text_he, normalize_he(text_he), text_en),
    )
