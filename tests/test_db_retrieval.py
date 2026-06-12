"""Offline tests of the DB layer + retrieval pipeline against synthetic fixture
rows (fixture text is test data, not real Torah text — real content comes from
the Sefaria ingestion)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, retrieval  # noqa: E402

FIXTURES = [
    dict(sefer="Shulchan Aruch", category="shulchan_aruch",
         ref="Shulchan Aruch YD 198:1", siman=198, seif=1,
         text_he="טקסט בדיקה על חציצה בטבילה ורוב שערה"),
    dict(sefer="Shach", category="acharon",
         ref="Shach YD 201:5:3", siman=201, seif=5,
         text_he="טקסט בדיקה על מים שאובין וזוחלין במקוה"),
    dict(sefer="Shulchan Aruch", category="shulchan_aruch",
         ref="Shulchan Aruch YD 201:5", siman=201, seif=5,
         text_he="טקסט בדיקה על שיעור ארבעים סאה"),
    dict(sefer="Gemara Niddah", category="gemara",
         ref="Niddah 66b:2",
         text_he="טקסט בדיקה בגמרא על חפיפה"),
    dict(sefer="Mishnayos Mikvaos", category="mishna",
         ref="Mishnah Mikvaos 2:3",
         text_he="טקסט בדיקה במשנה על ספק מים שאובין",
         text_en="test text about doubtful drawn water"),
    dict(sefer="Bartenura", category="rishon",
         ref="Bartenura Mikvaos 2:3:1",
         text_he="טקסט בדיקה של פירוש על המשנה"),
]


class TestRetrieval(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        for f in FIXTURES:
            db.insert_text(self.conn, **f)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def refs_for(self, question):
        rows, _ = retrieval.retrieve(self.conn, question)
        return [r["ref"] for r in rows]

    def test_direct_siman_seif_lookup(self):
        refs = self.refs_for("what does the Shach say in 201:5?")
        self.assertIn("Shach YD 201:5:3", refs)
        self.assertIn("Shulchan Aruch YD 201:5", refs)

    def test_siman_only_pulls_all_seifim(self):
        refs = self.refs_for("everything on siman 201")
        self.assertIn("Shach YD 201:5:3", refs)
        self.assertIn("Shulchan Aruch YD 201:5", refs)

    def test_gemara_lookup(self):
        refs = self.refs_for("Niddah 66b")
        self.assertIn("Niddah 66b:2", refs)

    def test_mishnah_lookup_includes_meforshim(self):
        refs = self.refs_for("the mishnah Mikvaos 2:3")
        self.assertIn("Mishnah Mikvaos 2:3", refs)
        self.assertIn("Bartenura Mikvaos 2:3:1", refs)

    def test_fts_hebrew_keyword(self):
        refs = self.refs_for("מה הדין של חציצה?")
        self.assertIn("Shulchan Aruch YD 198:1", refs)

    def test_fts_hebrew_keyword_nikud_insensitive(self):
        # query with nikud should still match the plain-text column
        refs = self.refs_for("חֲצִיצָה בטבילה")
        self.assertIn("Shulchan Aruch YD 198:1", refs)

    def test_fts_english_keyword(self):
        refs = self.refs_for("doubtful drawn water")
        self.assertIn("Mishnah Mikvaos 2:3", refs)

    def test_upsert_by_ref(self):
        db.insert_text(self.conn, sefer="Shach", category="acharon",
                       ref="Shach YD 201:5:3", siman=201, seif=5,
                       text_he="טקסט מעודכן על שאובין")
        self.conn.commit()
        n = self.conn.execute(
            "SELECT count(*) c FROM texts WHERE ref='Shach YD 201:5:3'"
        ).fetchone()["c"]
        self.assertEqual(n, 1)
        row = self.conn.execute(
            "SELECT text_he FROM texts WHERE ref='Shach YD 201:5:3'").fetchone()
        self.assertIn("מעודכן", row["text_he"])

    def test_normalize_strips_html_and_nikud(self):
        self.assertEqual(db.normalize_he("<b>שָׁלוֹם</b>  עולם"), "שלום עולם")


if __name__ == "__main__":
    unittest.main()
