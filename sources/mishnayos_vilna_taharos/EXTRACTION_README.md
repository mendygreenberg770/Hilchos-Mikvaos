# מערכת חילוץ טקסט — משניות דפוס וילנא (צורת הדף)

## What this is
A pipeline that extracts properly-ordered Hebrew text from born-digital
Vilna-layout seforim PDFs and segments each page by commentary:
משנה · ר"ש משאנץ · פירוש המשניות לרמב"ם · פירוש הרא"ש · עין משפט · הגהות/ילקוטים.

Key point: these PDFs have a *correct* embedded text layer (real Vilna and
Rashi fonts, logical RTL order). The gibberish from ordinary extractors is
a reading-order bug, not an OCR problem — no OCR needed; the girsa is
letter-for-letter what's printed.

## Marker convention (tziyunim)
The small reference letters printed in middle of the text — the tziyunim
in the mishna pointing to the ר"ש/רא"ש pieces, the bracketed ]א[ letters
pointing to hagahos, and the piska letters before a dibur hamatchil — are
rendered as ⟨א⟩ tags. They are markers, not text. Bold **…** marks actual
dibur-hamatchil headers and printed mishna numerals. To strip markers
entirely, set "marks": "drop" in a config file.

## Using it on other seforim (not just this edition)
1. Profile the new file first — prints each page's font/size/position map:
       python3 seforim_extract.py "new_sefer.pdf" --profile
2. From that table, identify: the main-text font+size, the header line,
   margins, and section title text. Write a small JSON config overriding
   the defaults (any subset of the CONFIG keys at the top of the script):
       {"mishna_font": "Vilna", "mishna_min_size": 12,
        "rosh_title": "פירוש\\s*הרא", "marks": "tag"}
3. Run:
       python3 seforim_extract.py "new_sefer.pdf" --config my.json -o out
The column-side detection reads each page's running header, so facing-page
mirroring is handled automatically wherever the volume prints column titles.

## Output
  page_NNN.md      per page, per section, human-readable
  full.md          everything concatenated
  records.jsonl    one chunk per (page, section):
                   {source, pdf_page, daf, title, section, text}
                   → feeds straight into the RAG build spec's ingestion
                   step; the **bold** diburim are natural sub-chunk splits.

## Known limitations (review checklist)
- Long marginal yalkutim are grouped under one "הגהות וילקוטים" section
  rather than split by sub-heading.
- An occasional large bold numeral may sit one line off from where it's
  printed; the text itself is complete.
- A new edition needs its font map verified via --profile before a full run.
- For girsa-critical use, spot-check ~1 page per 10 against the PDF.
