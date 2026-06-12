"""The works to ingest from Sefaria, with chunking/ref rules.

Each entry:
  key           — short id for --works selection
  sefaria_title — exact Sefaria index title
  sefer         — display name stored in the texts table
  category      — shulchan_aruch / acharon / rishon / mishna / gemara / rambam
  ref_fmt       — canonical ref; {s}=section (siman/perek/daf), {1}/{2}=1-indexed
                  positions inside the section's (possibly nested) array
  sections      — list of section identifiers to fetch (None = fetch whole work)
  siman_seif    — if True, store siman=int(section), seif=first index (enables
                  the "everything on 201:5" lookups)

If a Sefaria title is off, the ingestion script reports the failure and moves on —
fix the title here and re-run (re-runs upsert by ref, so they're safe).
"""

SA_SIMANIM = [str(s) for s in range(198, 203)]          # YD 198-202
NIDDAH_DAPIM = ["66a", "66b", "67a", "67b"]             # hefsek/chafifa/chatzitza/tevillah
CHAGIGAH_DAPIM = ["18b", "19a"]                          # gud achis, tevillah b'mei mearah

WORKS = [
    {
        "key": "sa",
        "sefaria_title": "Shulchan Arukh, Yoreh De'ah",
        "sefer": "Shulchan Aruch",
        "category": "shulchan_aruch",
        "ref_fmt": "Shulchan Aruch YD {s}:{1}",
        "sections": SA_SIMANIM,
        "siman_seif": True,
    },
    {
        "key": "shach",
        "sefaria_title": "Siftei Kohen on Shulchan Arukh, Yoreh De'ah",
        "sefer": "Shach",
        "category": "acharon",
        "ref_fmt": "Shach YD {s}:{1}:{2}",
        "sections": SA_SIMANIM,
        "siman_seif": True,
    },
    {
        "key": "taz",
        "sefaria_title": "Turei Zahav on Shulchan Arukh, Yoreh De'ah",
        "sefer": "Taz",
        "category": "acharon",
        "ref_fmt": "Taz YD {s}:{1}:{2}",
        "sections": SA_SIMANIM,
        "siman_seif": True,
    },
    {
        "key": "beer_heitev",
        "sefaria_title": "Be'er Hetev on Shulchan Arukh, Yoreh De'ah",
        "sefer": "Be'er Heitev",
        "category": "acharon",
        "ref_fmt": "Be'er Heitev YD {s}:{1}:{2}",
        "sections": SA_SIMANIM,
        "siman_seif": True,
    },
    {
        "key": "pischei_teshuva",
        "sefaria_title": "Pithei Teshuva on Shulchan Arukh, Yoreh De'ah",
        "sefer": "Pischei Teshuva",
        "category": "acharon",
        "ref_fmt": "Pischei Teshuva YD {s}:{1}:{2}",
        "sections": SA_SIMANIM,
        "siman_seif": True,
    },
    {
        "key": "mishnah",
        "sefaria_title": "Mishnah Mikvaot",
        "sefer": "Mishnayos Mikvaos",
        "category": "mishna",
        "ref_fmt": "Mishnah Mikvaos {s}:{1}",
        "sections": [str(c) for c in range(1, 11)],
    },
    {
        "key": "bartenura",
        "sefaria_title": "Bartenura on Mishnah Mikvaot",
        "sefer": "Bartenura",
        "category": "rishon",
        "ref_fmt": "Bartenura Mikvaos {s}:{1}:{2}",
        "sections": [str(c) for c in range(1, 11)],
    },
    {
        "key": "tos_yom_tov",
        "sefaria_title": "Tosafot Yom Tov on Mishnah Mikvaot",
        "sefer": "Tosfos Yom Tov",
        "category": "acharon",
        "ref_fmt": "Tosfos Yom Tov Mikvaos {s}:{1}:{2}",
        "sections": [str(c) for c in range(1, 11)],
    },
    {
        "key": "rambam",
        "sefaria_title": "Mishneh Torah, Immersion Pools",
        "sefer": "Rambam Hilchos Mikvaos",
        "category": "rambam",
        "ref_fmt": "Rambam Mikvaos {s}:{1}",
        "sections": [str(c) for c in range(1, 12)],
    },
    {
        "key": "niddah",
        "sefaria_title": "Niddah",
        "sefer": "Gemara Niddah",
        "category": "gemara",
        "ref_fmt": "Niddah {s}:{1}",
        "sections": NIDDAH_DAPIM,
    },
    {
        "key": "rashi_niddah",
        "sefaria_title": "Rashi on Niddah",
        "sefer": "Rashi",
        "category": "rishon",
        "ref_fmt": "Rashi Niddah {s}:{1}:{2}",
        "sections": NIDDAH_DAPIM,
    },
    {
        "key": "tosafos_niddah",
        "sefaria_title": "Tosafot on Niddah",
        "sefer": "Tosfos",
        "category": "rishon",
        "ref_fmt": "Tosfos Niddah {s}:{1}:{2}",
        "sections": NIDDAH_DAPIM,
    },
    {
        "key": "chagigah",
        "sefaria_title": "Chagigah",
        "sefer": "Gemara Chagigah",
        "category": "gemara",
        "ref_fmt": "Chagigah {s}:{1}",
        "sections": CHAGIGAH_DAPIM,
    },
    {
        "key": "rashi_chagigah",
        "sefaria_title": "Rashi on Chagigah",
        "sefer": "Rashi",
        "category": "rishon",
        "ref_fmt": "Rashi Chagigah {s}:{1}:{2}",
        "sections": CHAGIGAH_DAPIM,
    },
    {
        # Rosh, Hilchos Mikvaos (printed after Niddah). If this Sefaria title
        # 404s, check sefaria.org for the exact index title and update here.
        "key": "rosh",
        "sefaria_title": "Hilkhot Mikvaot",
        "sefer": "Rosh Hilchos Mikvaos",
        "category": "rishon",
        "ref_fmt": "Rosh Mikvaos {s}:{1}",
        "sections": None,
    },
]
