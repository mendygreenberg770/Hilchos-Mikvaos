"""Sefaria ingestion: walk each configured work, chunk by seif/mishnah/segment,
store rows with exact structured refs.

Uses the classic texts API: GET /api/texts/{tref}?context=0&commentary=0&pad=0
which returns {"he": [...], "text": [...]} — possibly nested lists for
commentaries (seif -> [s"k, s"k, ...]).
"""

import time
import urllib.parse

import httpx

from app import db
from .works import WORKS

API_BASE = "https://www.sefaria.org/api/texts/"
HEADERS = {"User-Agent": "HilchosMikvaosResearch/1.0 (personal Torah research tool)"}


def fetch_tref(tref: str, retries: int = 3) -> dict:
    url = API_BASE + urllib.parse.quote(tref) + "?context=0&commentary=0&pad=0"
    last = None
    for attempt in range(retries):
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
            if resp.status_code == 404:
                raise LookupError(f"Sefaria 404 for {tref!r} — check the index title")
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise LookupError(f"Sefaria error for {tref!r}: {data['error']}")
            return data
        except LookupError:
            raise
        except Exception as e:  # network hiccup — back off and retry
            last = e
            time.sleep(2 ** attempt)
    raise last


def flatten(he, en, path=()):
    """Walk parallel nested lists, yielding (path, he_text, en_text) leaves.
    Paths are 0-indexed tuples; en may be missing/shorter than he."""
    if isinstance(he, str):
        if he.strip():
            yield path, he, (en if isinstance(en, str) and en.strip() else None)
        return
    if isinstance(he, list):
        for i, h in enumerate(he):
            e = en[i] if isinstance(en, list) and i < len(en) else None
            yield from flatten(h, e, path + (i,))


def _build_ref(ref_fmt: str, section: str, path: tuple) -> str:
    ref = ref_fmt.replace("{s}", section)
    for n in (1, 2, 3):
        token = "{%d}" % n
        if token in ref:
            if len(path) >= n:
                ref = ref.replace(token, str(path[n - 1] + 1))
            else:
                # shallower than expected (e.g. a seif with a single unnested
                # comment) — drop the trailing level
                ref = ref.rstrip(":").replace(":" + token, "").replace(token, "")
    return ref


def ingest_work(conn, work: dict, verbose: bool = True) -> tuple[int, list[str]]:
    """Returns (rows_stored, errors)."""
    stored, errors = 0, []
    sections = work["sections"] or [None]
    for section in sections:
        tref = work["sefaria_title"] + (f".{section}" if section else "")
        try:
            data = fetch_tref(tref)
        except Exception as e:
            errors.append(f"{tref}: {e}")
            continue
        he, en = data.get("he", []), data.get("text", [])
        sec_label = section or "1"
        count = 0
        for path, he_text, en_text in flatten(he, en):
            ref = _build_ref(work["ref_fmt"], sec_label, path)
            siman = seif = None
            if work.get("siman_seif") and section is not None:
                siman = int(section)
                seif = path[0] + 1 if path else None
            db.insert_text(
                conn,
                sefer=work["sefer"],
                category=work["category"],
                ref=ref,
                sefaria_ref=f"{tref}:{':'.join(str(p + 1) for p in path)}" if path else tref,
                siman=siman,
                seif=seif,
                text_he=db.strip_html(he_text).strip(),
                text_en=db.strip_html(en_text).strip() if en_text else None,
            )
            count += 1
        stored += count
        if verbose:
            print(f"  {tref}: {count} chunks")
        conn.commit()
        time.sleep(0.3)  # be polite to Sefaria
    return stored, errors


def ingest(work_keys: list[str] | None = None, db_path=None, verbose: bool = True):
    conn = db.connect(db_path)
    selected = [w for w in WORKS if not work_keys or w["key"] in work_keys]
    if work_keys:
        unknown = set(work_keys) - {w["key"] for w in WORKS}
        if unknown:
            raise SystemExit(f"unknown work keys: {', '.join(sorted(unknown))}")
    summary = []
    for work in selected:
        if verbose:
            print(f"\n=== {work['sefer']} ({work['sefaria_title']}) ===")
        stored, errors = ingest_work(conn, work, verbose=verbose)
        summary.append((work["key"], stored, errors))
    conn.close()

    print("\n--- Summary ---")
    ok = True
    for key, stored, errors in summary:
        status = f"{stored} chunks"
        if errors:
            ok = False
            status += f", {len(errors)} ERRORS"
        print(f"  {key:18s} {status}")
        for err in errors:
            print(f"      ! {err}")
    if not ok:
        print("\nSome works failed — usually a Sefaria index-title mismatch. "
              "Fix the title in ingest/works.py and re-run (re-runs are safe).")
    return summary
