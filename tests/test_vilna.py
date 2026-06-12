"""Tests for the Vilna mishnayos extraction ingester, run against the real
committed records.jsonl (offline — no network)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from ingest.vilna import (  # noqa: E402
    anchor_value, ingest_vilna, load_records, numeral_value, parse_commentary,
    parse_mishnayos, title_chapter,
)

RECORDS = ROOT / "sources" / "mishnayos_vilna_taharos" / "records.jsonl"

# standard Vilna mishna counts for Maseches Mikvaos
EXPECTED_COUNTS = {1: 8, 2: 10, 3: 4, 4: 5, 5: 6, 6: 11, 7: 7, 8: 5, 9: 7, 10: 8}


class TestHelpers(unittest.TestCase):
    def test_numeral_value(self):
        self.assertEqual(numeral_value("א"), 1)
        self.assertEqual(numeral_value("⟨ה⟩"), 5)
        self.assertEqual(numeral_value("יא"), 11)
        self.assertIsNone(numeral_value("אכל"))   # a word, not a numeral
        self.assertIsNone(numeral_value("כ"))     # > 19, never a mishna number here

    def test_anchor_value_multi(self):
        self.assertEqual(anchor_value("ז ח ⟨ט⟩"), 7)
        self.assertIsNone(anchor_value("מי גבים."))

    def test_title_chapter(self):
        self.assertEqual(title_chapter("שש מעלות פרק ראשון מקוואות"), 1)
        self.assertEqual(title_chapter("רב האי גאוןפירוש מקוואות פרק עשירי כל ידות"), 10)


@unittest.skipUnless(RECORDS.exists(), "records.jsonl not present")
class TestVilnaParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = load_records(RECORDS)

    def test_mishna_counts_match_standard(self):
        rows = parse_mishnayos(self.recs, verbose=False)
        counts = {}
        for r in rows:
            counts[r["chapter"]] = max(counts.get(r["chapter"], 0), r["mishna"])
        self.assertEqual(counts, EXPECTED_COUNTS)
        self.assertEqual(len(rows), sum(EXPECTED_COUNTS.values()))

    def test_known_mishna_openings(self):
        rows = {(r["chapter"], r["mishna"]): r["text"]
                for r in parse_mishnayos(self.recs, verbose=False)}
        self.assertTrue(rows[(1, 1)].startswith("שש מעלות"))
        self.assertTrue(rows[(1, 5)].startswith("מאימתי טהרתן"))
        self.assertTrue(rows[(7, 1)].startswith("יש מעלין"))
        self.assertTrue(rows[(9, 1)].startswith("אלו חוצצין"))

    def test_no_markup_left_in_text(self):
        for r in parse_mishnayos(self.recs, verbose=False):
            self.assertNotIn("**", r["text"])
            self.assertNotIn("⟨", r["text"])

    def test_commentary_covers_all_chapters(self):
        for section in ('ר"ש משאנץ', 'פירוש המשניות לרמב"ם', 'פירוש הרא"ש'):
            chunks = parse_commentary(self.recs, section, verbose=False)
            self.assertGreater(len(chunks), 150, section)
            self.assertEqual({c["chapter"] for c in chunks},
                             set(range(1, 11)), section)

    def test_known_dibur_lands_on_its_mishna(self):
        # mishna 2:3 opens "ספק מים שאובין שטהרו חכמים" — the Rash dibur on it
        chunks = parse_commentary(self.recs, 'ר"ש משאנץ', verbose=False)
        hit = [c for c in chunks
               if c["head"] and c["head"].startswith("ספק מים שאובין")]
        self.assertTrue(hit)
        self.assertEqual((hit[0]["chapter"], hit[0]["mishna"]), (2, 3))


@unittest.skipUnless(RECORDS.exists(), "records.jsonl not present")
class TestVilnaIngestion(unittest.TestCase):
    def test_replaces_mishna_keeps_english(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.db"
            conn = db.connect(path)
            # pre-existing Sefaria-style row with an English translation
            db.insert_text(conn, sefer="Mishnayos Mikvaos", category="mishna",
                           ref="Mishnah Mikvaos 1:1",
                           text_he="נוסח ישן", text_en="old english translation")
            # a row the extraction does NOT cover must remain untouched
            db.insert_text(conn, sefer="Shulchan Aruch", category="shulchan_aruch",
                           ref="Shulchan Aruch YD 201:5", siman=201, seif=5,
                           text_he="טקסט של שולחן ערוך")
            conn.commit()
            conn.close()

            ingest_vilna(RECORDS, db_path=path, verbose=False)

            conn = db.connect(path)
            row = conn.execute(
                "SELECT * FROM texts WHERE ref='Mishnah Mikvaos 1:1'").fetchone()
            self.assertTrue(row["text_he"].startswith("שש מעלות"))   # replaced
            self.assertEqual(row["text_en"], "old english translation")  # kept
            sa = conn.execute(
                "SELECT text_he FROM texts WHERE ref='Shulchan Aruch YD 201:5'").fetchone()
            self.assertEqual(sa["text_he"], "טקסט של שולחן ערוך")    # untouched
            n = conn.execute(
                "SELECT count(*) c FROM texts WHERE sefer='Mishnayos Mikvaos'").fetchone()["c"]
            self.assertEqual(n, 71)
            conn.close()


if __name__ == "__main__":
    unittest.main()
