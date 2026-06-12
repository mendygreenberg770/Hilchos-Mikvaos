"""Ingest the Vilna-layout Mishnayos extraction (records.jsonl from
tools/seforim_extract.py) — the mishna text itself plus the on-daf meforshim:
ר"ש משאנץ, פירוש המשניות לרמב"ם, פירוש הרא"ש, עין משפט, הגהות וילקוטים.

Mishna numbering is reconstructed from the printed evidence:
  - mishnayos are separated by the sof-mishna colon ":"
  - bold numerals (**⟨X⟩** or **X**) anchor segment -> mishna-number mapping
  - chapter boundaries are where the anchor arithmetic resets, cross-checked
    against the page running headers (chapters start mid-page in this layout)

Mishna rows REPLACE existing rows with the same ref ("Mishnah Mikvaos c:m"),
i.e. exactly the mishnayos this extraction has — any existing English
translation (from Sefaria) is preserved. Commentary rows are replaced
wholesale per sefer (delete + insert) so re-runs never leave stale chunks.
"""

import json
import re
from pathlib import Path

from app import db

ORDINALS = {
    "ראשון": 1, "שני": 2, "שלישי": 3, "רביעי": 4, "חמישי": 5,
    "ששי": 6, "שביעי": 7, "שמיני": 8, "תשיעי": 9, "עשירי": 10,
}

_UNITS = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9}

BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
TAG_RE = re.compile(r"⟨[^⟩]*⟩")
PEREK_HDR_RE = re.compile(r"^פרק\s+([א-י])$")

MISHNA_SECTION = "משנה"
COMMENTARIES = {
    'ר"ש משאנץ': dict(sefer="Rash MiShantz", category="rishon",
                      prefix="Rash Mikvaos"),
    'פירוש המשניות לרמב"ם': dict(sefer="Pirush HaMishnayos LehaRambam",
                                 category="rishon", prefix="Rambam PHM Mikvaos"),
    'פירוש הרא"ש': dict(sefer="Pirush HaRosh", category="rishon",
                        prefix="Pirush HaRosh Mikvaos"),
}
MARGINALIA = {
    'עין משפט': dict(sefer="Ein Mishpat", category="reference",
                     prefix="Ein Mishpat Mikvaos"),
    'הגהות וילקוטים (שולי הדף)': dict(sefer="Hagahos VeYalkutim", category="acharon",
                                      prefix="Hagahos Mikvaos"),
}


def title_chapter(title: str) -> int | None:
    m = re.search(r"פרק\s+(\S+)", title)
    return ORDINALS.get(m.group(1)) if m else None


def numeral_value(s: str) -> int | None:
    """Value of a printed mishna numeral: a single unit letter, 'י', or 'י'+unit.
    Deliberately tight (max 19) so bold words are never misread as numerals."""
    s = TAG_RE.sub(lambda m: m.group(0)[1:-1], s).strip()  # unwrap ⟨X⟩
    s = s.strip("⟨⟩ \n")
    if not s:
        return None
    if s in _UNITS:
        return _UNITS[s]
    if s == "י":
        return 10
    if len(s) == 2 and s[0] == "י" and s[1] in _UNITS:
        return 10 + _UNITS[s[1]]
    return None


def anchor_value(bold_text: str) -> int | None:
    """A bold run is a numeral anchor iff every whitespace-separated token is a
    numeral (a run like 'ז ח ⟨ט⟩' marks pieces for several mishnayos — the
    following text starts at the first). Returns the first value."""
    tokens = bold_text.split()
    if not tokens:
        return None
    vals = [numeral_value(t) for t in tokens]
    if all(v is not None for v in vals):
        return vals[0]
    return None


def clean(text: str) -> str:
    text = TAG_RE.sub(" ", text)
    text = text.replace("**", " ")
    text = text.replace("=", " ")
    return re.sub(r"\s+", " ", text).strip(" \n:")


def load_records(path: Path) -> list[dict]:
    recs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return sorted(recs, key=lambda r: r["pdf_page"])


# ---------------------------------------------------------------------------
# Mishna parsing
# ---------------------------------------------------------------------------

def parse_mishnayos(recs: list[dict], verbose: bool = True) -> list[dict]:
    """Returns [{"chapter", "mishna", "text", "page"}] for every mishna."""
    ms = [r for r in recs if r["section"] == MISHNA_SECTION]
    chapter_first_page = {}
    for r in ms:
        c = title_chapter(r["title"])
        if c:
            chapter_first_page.setdefault(c, r["pdf_page"])

    # one continuous stream with page offsets
    stream = ""
    page_marks = []
    for r in ms:
        if stream:
            stream += "\n"
        page_marks.append((len(stream), r["pdf_page"]))
        stream += r["text"]

    def page_of(offset: int) -> int:
        page = page_marks[0][1]
        for off, pg in page_marks:
            if offset >= off:
                page = pg
        return page

    # colon-separated segments with absolute offsets
    segments = []
    pos = 0
    for part in stream.split(":"):
        if part.strip():
            segments.append({"off": pos, "raw": part})
        pos += len(part) + 1

    def segment_index(offset: int) -> int | None:
        for i, seg in enumerate(segments):
            if seg["off"] <= offset < seg["off"] + len(seg["raw"]) + 1:
                return i
        return None

    # bold numeral anchors -> (segment_index, value)
    anchors = []
    for m in BOLD_RE.finditer(stream):
        v = anchor_value(m.group(1))
        if v is not None:
            i = segment_index(m.start())
            if i is not None and (i, v) not in anchors:
                anchors.append((i, v))
    anchors.sort()

    # group anchors into linear blocks (seg - value constant, values increasing);
    # each block belongs to one chapter and pins its first-mishna segment
    blocks: list[list[tuple[int, int]]] = []
    for i, v in anchors:
        if blocks:
            pi, pv = blocks[-1][-1]
            if i - v == pi - pv and v >= pv:
                blocks[-1].append((i, v))
                continue
        blocks.append([(i, v)])

    # merge blocks that imply the same chapter start; then drop singleton
    # outliers wedged between agreeing neighbours (stray/duplicate numerals)
    def start_of(block):
        return block[0][0] - block[0][1] + 1

    merged: list[list[tuple[int, int]]] = []
    for b in blocks:
        if merged and start_of(b) == start_of(merged[-1]):
            merged[-1].extend(b)
        else:
            merged.append(b)
    repaired = []
    for k, b in enumerate(merged):
        if (len(b) == 1 and 0 < k < len(merged) - 1
                and start_of(merged[k - 1]) == start_of(merged[k + 1])):
            continue  # conflicting stray anchor
        if repaired and start_of(b) == start_of(repaired[-1]):
            repaired[-1].extend(b)
        else:
            repaired.append(b)

    starts = [start_of(b) for b in repaired]
    if starts and starts[0] != 0:
        starts[0] = 0  # chapter 1 starts at the first segment by definition

    n_chapters = len(chapter_first_page)
    if len(starts) != n_chapters:
        raise SystemExit(
            f"Mishna numbering reconstruction found {len(starts)} chapters, "
            f"expected {n_chapters} (from page titles). Anchors: {anchors}")

    # cross-check chapter starts against the running headers
    for c, start in enumerate(starts, 1):
        seg_page = page_of(segments[start]["off"])
        title_page = chapter_first_page[c]
        if not (title_page - 1 <= seg_page <= title_page + 1):
            print(f"  WARNING: chapter {c} starts on page {seg_page} but page "
                  f"titles say {title_page} — verify against the PDF")

    out = []
    bounds = starts + [len(segments)]
    for c in range(1, n_chapters + 1):
        for m, idx in enumerate(range(bounds[c - 1], bounds[c]), 1):
            seg = segments[idx]
            out.append({"chapter": c, "mishna": m,
                        "text": clean(seg["raw"]),
                        "page": page_of(seg["off"])})
    if verbose:
        counts = {}
        for row in out:
            counts[row["chapter"]] = max(counts.get(row["chapter"], 0), row["mishna"])
        print(f"  mishnayos per perek: {counts}  (total {len(out)})")
    return out


# ---------------------------------------------------------------------------
# Commentary parsing
# ---------------------------------------------------------------------------

def parse_commentary(recs: list[dict], section: str, verbose: bool = True) -> list[dict]:
    """Split a commentary stream into dibur-hamatchil chunks, tracking
    (chapter, mishna) via bold פרק headers and numeral anchors.
    Returns [{"chapter", "mishna"|None, "head"|None, "text", "page"}]."""
    rows = [r for r in recs if r["section"] == section]
    chunks: list[dict] = []
    chapter, mishna = 1, None
    current: dict | None = None

    def flush():
        nonlocal current
        if current:
            text = clean(current["text"])
            # drop residue like a bare פ"א marker between real chunks
            if len(text) >= 15:
                current["text"] = text
                chunks.append(current)
        current = None

    def append_text(t: str, page: int):
        nonlocal current
        if current is None:
            current = {"chapter": chapter, "mishna": mishna, "head": None,
                       "text": "", "page": page}
        current["text"] += " " + t

    for r in rows:
        page = r["pdf_page"]
        pc = title_chapter(r["title"]) or chapter
        # commentary spillover is at most one chapter behind the page header
        if chapter < pc - 1:
            flush()
            chapter, mishna = pc - 1, None
        text = r["text"]
        pos = 0
        for m in BOLD_RE.finditer(text):
            if m.start() > pos:
                append_text(text[pos:m.start()], page)
            content = m.group(1).replace("\n", " ").strip()
            hdr = PEREK_HDR_RE.match(content)
            val = anchor_value(content)
            if hdr:                                   # explicit chapter header
                flush()
                chapter = _UNITS.get(hdr.group(1), 10 if hdr.group(1) == "י" else None) or chapter
                mishna = None
            elif val is not None:                     # mishna-numeral anchor
                flush()
                if mishna is not None and val < mishna and chapter < pc:
                    chapter += 1                      # numbering reset = new perek
                mishna = val
            elif re.sub(r"[^\wא-ת]", "", content):    # dibur hamatchil
                flush()
                head_words = clean(content).split()
                current = {"chapter": chapter, "mishna": mishna,
                           "head": " ".join(head_words[:5]).strip(".,"),
                           "text": "", "page": page}
            # bold punctuation-only runs are ignored
            pos = m.end()
        if pos < len(text):
            append_text(text[pos:], page)
    flush()
    if verbose:
        print(f"  {section}: {len(chunks)} chunks")
    return chunks


def parse_marginalia(recs: list[dict], section: str, max_len: int = 3000) -> list[dict]:
    """One chunk per page (split at colon boundaries when very long)."""
    out = []
    for r in recs:
        if r["section"] != section:
            continue
        chapter = title_chapter(r["title"])
        text = clean(r["text"])
        if not text:
            continue
        parts = [text]
        while any(len(p) > max_len for p in parts):
            big = max(parts, key=len)
            i = parts.index(big)
            cut = big.rfind(":", 0, max_len)
            cut = cut if cut > 0 else max_len
            parts[i:i + 1] = [big[:cut].strip(), big[cut + 1:].strip()]
        for j, p in enumerate(parts, 1):
            out.append({"chapter": chapter, "page": r["pdf_page"],
                        "part": j if len(parts) > 1 else None, "text": p})
    return out


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _upsert_mishna_keep_en(conn, ref, text_he, source):
    """Replace the Hebrew text of exactly this mishna; keep any existing
    English translation and don't touch rows this extraction doesn't have."""
    conn.execute(
        """INSERT INTO texts (sefer, category, ref, sefaria_ref, siman, seif,
                              text_he, text_he_plain, text_en)
           VALUES ('Mishnayos Mikvaos', 'mishna', ?, ?, NULL, NULL, ?, ?, NULL)
           ON CONFLICT(ref) DO UPDATE SET
             sefer=excluded.sefer, category=excluded.category,
             sefaria_ref=excluded.sefaria_ref,
             text_he=excluded.text_he, text_he_plain=excluded.text_he_plain,
             text_en=COALESCE(texts.text_en, excluded.text_en)""",
        (ref, source, text_he, db.normalize_he(text_he)))


def ingest_vilna(records_path, db_path=None, verbose: bool = True):
    records_path = Path(records_path)
    recs = load_records(records_path)
    source_name = recs[0].get("source", records_path.parent.name)
    conn = db.connect(db_path)

    if verbose:
        print(f"=== Mishnayos (replacing exact mishnayos present) ===")
    mishnayos = parse_mishnayos(recs, verbose=verbose)
    for m in mishnayos:
        ref = f"Mishnah Mikvaos {m['chapter']}:{m['mishna']}"
        _upsert_mishna_keep_en(conn, ref, m["text"],
                               f"{source_name}:p{m['page']}")
    conn.commit()

    if verbose:
        print("=== Meforshim ===")
    for section, meta in COMMENTARIES.items():
        conn.execute("DELETE FROM texts WHERE sefer=?", (meta["sefer"],))
        seen: dict[str, int] = {}
        for ch in parse_commentary(recs, section, verbose=verbose):
            base = f"{meta['prefix']} {ch['chapter']}"
            if ch["mishna"]:
                base += f":{ch['mishna']}"
            if ch["head"]:
                base += f' ד"ה {ch["head"]}'
            seen[base] = seen.get(base, 0) + 1
            ref = base if seen[base] == 1 else f"{base} ({seen[base]})"
            db.insert_text(conn, sefer=meta["sefer"], category=meta["category"],
                           ref=ref, text_he=ch["text"],
                           sefaria_ref=f"{source_name}:p{ch['page']}")
        conn.commit()

    for section, meta in MARGINALIA.items():
        conn.execute("DELETE FROM texts WHERE sefer=?", (meta["sefer"],))
        count = 0
        for ch in parse_marginalia(recs, section):
            ref = f"{meta['prefix']} פרק {ch['chapter']} (עמ' {ch['page']}"
            ref += f".{ch['part']})" if ch["part"] else ")"
            db.insert_text(conn, sefer=meta["sefer"], category=meta["category"],
                           ref=ref, text_he=ch["text"],
                           sefaria_ref=f"{source_name}:p{ch['page']}")
            count += 1
        conn.commit()
        if verbose:
            print(f"  {section}: {count} chunks")

    if verbose:
        total = conn.execute("SELECT count(*) c FROM texts").fetchone()["c"]
        print(f"\nLibrary now holds {total} chunks.")
    conn.close()
