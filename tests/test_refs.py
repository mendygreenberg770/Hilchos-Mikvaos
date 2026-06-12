import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.refs import Ref, detect_refs, hebrew_to_int  # noqa: E402


class TestGematria(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(hebrew_to_int("א"), 1)
        self.assertEqual(hebrew_to_int("יה"), 15)
        self.assertEqual(hebrew_to_int("טו"), 15)
        self.assertEqual(hebrew_to_int("קצח"), 198)
        self.assertEqual(hebrew_to_int("רא"), 201)
        self.assertEqual(hebrew_to_int("רב"), 202)

    def test_with_quotes(self):
        self.assertEqual(hebrew_to_int('ר"א'), 201)
        self.assertEqual(hebrew_to_int("קצ״ח"), 198)

    def test_invalid(self):
        self.assertIsNone(hebrew_to_int(""))
        self.assertIsNone(hebrew_to_int("abc"))
        self.assertIsNone(hebrew_to_int("שלום עולם"))


class TestDetectRefs(unittest.TestCase):
    def test_numeric_siman_seif(self):
        refs = detect_refs("What does the Shach hold in 201:5?")
        self.assertIn(Ref(kind="sa", siman=201, seif=5), refs)

    def test_english_siman_seif_words(self):
        refs = detect_refs("see siman 198 seif 1 please")
        self.assertIn(Ref(kind="sa", siman=198, seif=1), refs)

    def test_bare_siman(self):
        refs = detect_refs("everything on siman 202")
        self.assertIn(Ref(kind="sa", siman=202), refs)

    def test_hebrew_siman_seif(self):
        refs = detect_refs("מה כתוב בסימן קצח סעיף א")
        self.assertIn(Ref(kind="sa", siman=198, seif=1), refs)

    def test_hebrew_compact(self):
        refs = detect_refs('עיין רא:ה בש"ך')
        self.assertIn(Ref(kind="sa", siman=201, seif=5), refs)

    def test_gemara_english(self):
        refs = detect_refs("the gemara Niddah 66b says")
        self.assertIn(Ref(kind="gemara", masechta="Niddah", daf="66b"), refs)

    def test_gemara_hebrew(self):
        refs = detect_refs("בגמרא נדה סו: מבואר")
        self.assertIn(Ref(kind="gemara", masechta="Niddah", daf="66b"), refs)

    def test_gemara_hebrew_amud_alef(self):
        refs = detect_refs("עיין חגיגה יט. שם")
        self.assertIn(Ref(kind="gemara", masechta="Chagigah", daf="19a"), refs)

    def test_mishnah(self):
        refs = detect_refs("the mishnah in Mikvaos 2:3")
        self.assertIn(Ref(kind="mishnah", chapter=2, mishnah=3), refs)

    def test_mishnah_hebrew(self):
        refs = detect_refs("במשנה מקואות ב:ג")
        self.assertIn(Ref(kind="mishnah", chapter=2, mishnah=3), refs)

    def test_no_false_positive_on_small_ratio(self):
        # "2:3" alone (no work name) should not be claimed as a siman
        refs = detect_refs("the ratio is 2:3 in that case")
        self.assertFalse(any(r.kind == "sa" for r in refs))

    def test_no_refs_in_plain_question(self):
        refs = detect_refs("מה הדין של חציצה בטבילה?")
        self.assertEqual(refs, [])

    def test_mishnah_not_double_counted_as_siman(self):
        refs = detect_refs("Mikvaos 2:3")
        self.assertEqual(len([r for r in refs if r.kind == "sa"]), 0)


if __name__ == "__main__":
    unittest.main()
