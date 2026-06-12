#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seforim_extract.py — Extract properly-ordered Hebrew text from Vilna-layout
(tzuras-hadaf) Mishnayos PDFs and segment it by commentary.

Designed for the Zecher Chanoch / digital-Vilna Mishnayos Seder Taharos PDFs:
born-digital files with embedded Vilna/Rashi fonts whose text layer is in
correct logical (RTL) order when read with PyMuPDF.

Layout model per page:
  - Running header (y < ~35): daf number, masechta/perek title, and the
    column titles (רמב"ם / ר"ש משאנץ / עין משפט / הגהות...) whose x-positions
    tell us which side each commentary is on (mirrored on facing pages).
  - Top band: Mishna text (large square Vilna font), mishna letters in bold.
  - Main band: two commentary columns (Rambam, R"Sh MiShantz) split at gutter.
  - Bottom band: Pirush HaRosh (detected by its title span).
  - Margins: Ein Mishpat, hagahos, yalkutim, etc.

Output:
  out/<stem>/page_NNN.md      — human-readable, per page, per section
  out/<stem>/full.md          — everything concatenated
  out/<stem>/records.jsonl    — one record per (page, section) chunk,
                                ready for RAG ingestion:
                                {source, daf, perek, section, text}

Usage:
  python3 seforim_extract.py input.pdf [-o outdir] [--pages 1-10]
"""
import argparse, json, os, re, sys, unicodedata
from collections import defaultdict

import fitz  # PyMuPDF

# ------------------------------------------------------------ configuration
# Defaults fit the digital-Vilna Mishnayos Seder Taharos edition.
# For a different sefer: run with --profile first, then override any of
# these via --config myconfig.json
CONFIG = {
    "header_y": 35,        # everything above this is the running header
    "left_margin_x": 118,  # line entirely left of this  -> left margin
    "right_margin_x": 497, # line entirely right of this -> right margin
    "mishna_font": "Vilna",
    "mishna_min_size": 11.5,
    "rosh_title": "פירוש\\s*הרא",
    "dh_fonts": ["VTIvri,Bold"],
    "marks": "tag",        # "tag" -> render tziyunim as ⟨א⟩ ; "drop" -> remove
    "mark_ratio": 0.78,    # span smaller than this × line size = tziyun marker
}
HEADER_Y = CONFIG["header_y"]
LEFT_MARGIN_X = CONFIG["left_margin_x"]
RIGHT_MARGIN_X = CONFIG["right_margin_x"]

MISHNA_FONT = ("Vilna",)          # large square font, size >= 12
MISHNA_MIN_SIZE = CONFIG["mishna_min_size"]
ROSH_TITLE_RE = re.compile(r"פירוש\s*הרא")
DH_FONTS = set(CONFIG["dh_fonts"])  # dibur-hamatchil bold headers
QUOTE_FONT = ("FrankRuehl,Bold",) # square quotations inside R"Sh (Tosefta)

HEB_LETTER_RE = re.compile(r"^[א-ת]['\"]?$")

GERESH_FIX = re.compile(r"\s*\"\s*")  # rejoin abbreviations split around gershayim


# ---------------------------------------------------------------- helpers
def spans_of(page):
    d = page.get_text("dict")
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                if s["text"].strip():
                    yield s


def parse_header(page):
    """Return (daf, title, columns) from the running header."""
    hs = [s for s in spans_of(page) if s["bbox"][1] < HEADER_Y]
    hs.sort(key=lambda s: s["bbox"][0])

    # glue fragments like רמב | " | ם back together by *actual* glyph gaps
    merged, cur, startx, prev_x1 = [], "", None, None
    for s in hs:
        x0, x1 = s["bbox"][0], s["bbox"][2]
        t = s["text"].strip()
        if prev_x1 is not None and x0 - prev_x1 < 6:
            cur += t
        else:
            if cur:
                merged.append((startx, cur))
            cur, startx = t, x0
        prev_x1 = x1
    if cur:
        merged.append((startx, cur))

    daf, title, cols = None, [], {}
    for x, t in merged:
        if re.fullmatch(r"[א-ת]{1,4}", t) and t not in ("הגהות",):
            daf = t                      # the Hebrew page number (שנח, שנט…)
        elif "רמב" in t:
            cols["rambam"] = x
        elif "משאנץ" in t:
            cols["rash"] = x
        elif "משפט" in t:
            cols["ein_mishpat"] = x
        elif "הרש" in t or t == "הגהות" or "מסורת" in t:
            cols.setdefault("margin_notes", x)
        elif "פרק" in t or "מקוואות" in t or "מסכת" in t or len(t) > 6:
            title.append(t)
    return daf, " ".join(title), cols


BRACKET_MIRROR = str.maketrans("()[]{}<>", ")(][}{><")

def clean(text):
    text = unicodedata.normalize("NFC", text)
    text = text.translate(BRACKET_MIRROR)
    text = re.sub(r"[A-Za-z_]+", "", text)   # stray marker glyphs in Hebrew text
    text = GERESH_FIX.sub('"', text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def line_record(ln):
    """Collapse a pymupdf line into (text, x0, x1, y, fontset, maxsize, spans)."""
    parts, fonts, mx = [], set(), 0
    for s in ln["spans"]:
        if not s["text"].strip():
            continue
        parts.append(s)
        fonts.add(s["font"])
        mx = max(mx, s["size"])
    if not parts:
        return None
    by_font = {}
    for s in parts:
        k = (s["font"], round(s["size"], 1))
        by_font[k] = by_font.get(k, 0) + len(s["text"].strip())
    (dom_font, dom_size) = max(by_font, key=by_font.get)
    x0 = min(s["bbox"][0] for s in parts)
    x1 = max(s["bbox"][2] for s in parts)
    y = sum(s["bbox"][1] for s in parts) / len(parts)
    bot = max(s["bbox"][3] for s in parts)
    return {"spans": parts, "x0": x0, "x1": x1, "y": y, "bot": bot, "fonts": fonts,
            "size": mx, "dom_font": dom_font, "dom_size": dom_size}


def render_line(rec, bold_mark=True):
    """Spans -> text. Spans whose glyph boxes touch are joined with no space
    (fixes split abbreviations and single-letter font switches); bold
    dibur-hamatchil headers wrapped in **…**."""
    MARK_RE = re.compile(r"^[\]\[()_]*[\u05d0-\u05ea]{1,2}[\]\[()_]*$")
    pieces, prev_x1, prev_bold = [], None, False
    for s in sorted(rec["spans"], key=lambda s: -s["bbox"][2]):  # RTL order
        t = s["text"]
        if not t.strip():
            continue
        # tziyun markers: tiny superscript letters pointing to a commentary,
        # or a lone small letter occupying its own line (piska/drop-cap ref)
        st = t.strip()
        lone_letter = (len(rec["spans"]) == 1 and s["size"] <= 9.9
                       and re.fullmatch(r"[\u05d0-\u05ea]{1,2}", st))
        if MARK_RE.match(st) and (
                s["size"] < CONFIG["mark_ratio"] * rec["dom_size"] or lone_letter):
            if CONFIG["marks"] == "tag":
                core = re.sub(r"[\]\[()_]", "", st)
                if core:
                    pieces.append(f"⟨{core}⟩")
            prev_x1 = s["bbox"][0]
            continue
        is_bold = bold_mark and (s["font"] in DH_FONTS or
                  (s["font"].endswith("Bold") and s["size"] > 9 and
                   s["font"].startswith(("Vilna", "VTIvri"))))
        gap_touch = prev_x1 is not None and (prev_x1 - s["bbox"][2]) < 1.2
        if gap_touch and is_bold == prev_bold and pieces and not pieces[-1].startswith("⟨"):
            pieces[-1] = pieces[-1] + t
        else:
            pieces.append(t)
        prev_x1, prev_bold = s["bbox"][0], is_bold
        if is_bold and pieces and (not gap_touch or len(pieces) == 1 or not pieces[-1].startswith("**")):
            pieces[-1] = "**" + pieces[-1].strip() + "**"
    text = " ".join(p.strip() for p in pieces if p.strip())
    text = re.sub(r"\*\*\s*\*\*", " ", text)
    # piska letters glued to a bold dibur-hamatchil: render as ⟨marker⟩
    text = re.sub(r"(?<![\u05d0-\u05ea\"'])([\u05d0-\u05ea])\*\* ", r"⟨\1⟩ **", text)
    return clean(text)


# ---------------------------------------------------------------- page logic
def process_page(page, pno):
    daf, title, cols = parse_header(page)
    d = page.get_text("dict")

    lines = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            r = line_record(ln)
            if r and r["y"] >= HEADER_Y - 5:
                lines.append(r)

    # ---- find the Rosh title to set the bottom band -----------------------
    rosh_y = None
    for r in lines:
        txt = "".join(s["text"] for s in r["spans"])
        if ROSH_TITLE_RE.search(txt) and r["size"] >= 11:
            rosh_y = r["y"]
            break

    # ---- which side is which? --------------------------------------------
    rambam_x = cols.get("rambam", 150)
    rash_x = cols.get("rash", 440)
    gutter = (rambam_x + rash_x) / 2 + 20   # header x is title start; nudge

    sections = defaultdict(list)   # name -> [line records]

    for r in lines:
        mid = (r["x0"] + r["x1"]) / 2
        fonts = r["fonts"]

        # margins
        if r["x1"] < LEFT_MARGIN_X:
            side = "ein_mishpat" if cols.get("ein_mishpat", 999) < 300 else "margin_notes"
            sections[side].append(r); continue
        if r["x0"] > RIGHT_MARGIN_X:
            side = "ein_mishpat" if cols.get("ein_mishpat", 0) > 300 else "margin_notes"
            sections[side].append(r); continue

        # mishna: line's chars-dominant font is plain Vilna at large size
        if r["dom_font"].startswith("Vilna") and "Bold" not in r["dom_font"] \
           and r["dom_size"] >= MISHNA_MIN_SIZE \
           and not ROSH_TITLE_RE.search("".join(s["text"] for s in r["spans"])):
            sections["mishna"].append(r); continue

        # rosh band
        if rosh_y is not None and r["y"] > rosh_y + 2:
            sections["rosh"].append(r); continue

        # main band: split by gutter, assign by header side
        if mid < gutter:
            name = "rambam" if rambam_x < rash_x else "rash"
        else:
            name = "rash" if rambam_x < rash_x else "rambam"
        sections[name].append(r)

    # ---- order + render ----------------------------------------------------
    out = {}
    for name, recs in sections.items():
        recs.sort(key=lambda r: (round(r["bot"] / 3), -r["x1"]))
        text = "\n".join(render_line(r) for r in recs)
        # join hard-wrapped lines into paragraphs at bold headers
        text = re.sub(r"\n(?!\*\*)", " ", text)
        text = re.sub(r"\s+\*\*", "\n**", text)
        out[name] = clean_section(text)

    return daf, title, out


def clean_section(text):
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


SECTION_TITLES = {
    "mishna":       "משנה",
    "rambam":       'פירוש המשניות לרמב"ם',
    "rash":         'ר"ש משאנץ',
    "rosh":         'פירוש הרא"ש',
    "ein_mishpat":  "עין משפט",
    "margin_notes": "הגהות וילקוטים (שולי הדף)",
}
ORDER = ["mishna", "rash", "rambam", "rosh", "ein_mishpat", "margin_notes"]


def profile(doc):
    """Font/size/position census of a few pages — the map you need to
    configure this script for a new sefer/edition."""
    import collections
    for pno in range(min(3, len(doc))):
        agg = collections.defaultdict(lambda: [0, 0.0, 0.0, ""])
        for s in spans_of(doc[pno]):
            n = len(s["text"].strip())
            k = (s["font"], round(s["size"], 1))
            a = agg[k]
            a[0] += n; a[1] += s["bbox"][0] * n; a[2] += s["bbox"][1] * n
            if not a[3] and n > 8:
                a[3] = s["text"][:45]
        print(f"=== page {pno+1}")
        for k, a in sorted(agg.items(), key=lambda x: -x[1][0]):
            if a[0] < 60:
                continue
            print(f"  {k}  chars={a[0]:>5}  avg_x={a[1]/a[0]:>4.0f}  "
                  f"avg_y={a[2]/a[0]:>4.0f}  | {a[3]}")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("--pages", default=None, help="e.g. 1-5 (1-based)")
    ap.add_argument("--config", default=None, help="JSON file overriding CONFIG")
    ap.add_argument("--profile", action="store_true",
                    help="print font/position table for sample pages and exit")
    args = ap.parse_args()
    if args.config:
        CONFIG.update(json.load(open(args.config)))
    if args.profile:
        profile(fitz.open(args.pdf)); return

    doc = fitz.open(args.pdf)
    stem = os.path.splitext(os.path.basename(args.pdf))[0]
    outdir = os.path.join(args.out, stem)
    os.makedirs(outdir, exist_ok=True)

    rng = range(len(doc))
    if args.pages:
        a, _, b = args.pages.partition("-")
        rng = range(int(a) - 1, int(b or a))

    records, full = [], []
    for pno in rng:
        daf, title, secs = process_page(doc[pno], pno)
        page_md = [f"# דף {daf or pno+1} — {title}".strip()]
        for name in ORDER:
            if name not in secs or not secs[name]:
                continue
            page_md.append(f"\n## {SECTION_TITLES[name]}\n")
            page_md.append(secs[name])
            records.append({
                "source": stem, "pdf_page": pno + 1, "daf": daf,
                "title": title, "section": SECTION_TITLES[name],
                "text": secs[name],
            })
        md = "\n".join(page_md)
        with open(os.path.join(outdir, f"page_{pno+1:03d}.md"), "w") as f:
            f.write(md)
        full.append(md)
        print(f"page {pno+1:>3}  daf={daf}  sections={[k for k in ORDER if k in secs]}")

    with open(os.path.join(outdir, "full.md"), "w") as f:
        f.write("\n\n---\n\n".join(full))
    with open(os.path.join(outdir, "records.jsonl"), "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(records)} records -> {outdir}/")


if __name__ == "__main__":
    main()
