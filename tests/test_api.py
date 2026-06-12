"""End-to-end API tests with the Claude calls mocked out (no network/keys).
Verifies the ask -> retrieve -> log -> tag -> filter -> export pipeline."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp = tempfile.mkdtemp()
os.environ["MIKVAOS_DB"] = str(Path(_tmp) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app import config  # noqa: E402
from app.main import app  # noqa: E402

config.DB_PATH = Path(os.environ["MIKVAOS_DB"])

FAKE_ANSWER = "תשובה לדוגמה עם ציון (Shach YD 201:5:3)."
FAKE_TAGS = {"refs": [{"siman": 201, "seif": 5}], "topics": ["sheuvin"]}


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = db.connect()
        db.insert_text(conn, sefer="Shach", category="acharon",
                       ref="Shach YD 201:5:3", siman=201, seif=5,
                       text_he="טקסט בדיקה על מים שאובין")
        db.insert_text(conn, sefer="Shulchan Aruch", category="shulchan_aruch",
                       ref="Shulchan Aruch YD 198:1", siman=198, seif=1,
                       text_he="טקסט בדיקה על חציצה")
        conn.commit()
        conn.close()
        cls.client = TestClient(app)

    def test_stats(self):
        r = self.client.get("/api/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["texts"], 2)

    def test_full_ask_flow(self):
        with patch("app.main.answer_question", return_value=(FAKE_ANSWER, "test-model")), \
             patch("app.main.tag_question", return_value=dict(FAKE_TAGS)):
            r = self.client.post("/api/ask", json={"question": "מה הדין בשו\"ע 201:5?"})
        self.assertEqual(r.status_code, 200)
        rec = r.json()
        self.assertEqual(rec["answer"], FAKE_ANSWER)
        self.assertIn("Shach YD 201:5:3", rec["sources_used"])
        self.assertIn({"siman": 201, "seif": 5}, rec["refs"])
        self.assertIn("sheuvin", rec["topics"])

        # appears in the log, filterable by siman and topic
        self.assertTrue(self.client.get("/api/questions?siman=201").json())
        self.assertTrue(self.client.get("/api/questions?topic=sheuvin").json())
        self.assertFalse(self.client.get("/api/questions?siman=199").json())

        # tag editing
        qid = rec["id"]
        r = self.client.patch(f"/api/questions/{qid}/tags",
                              json={"topics": ["zochalin"],
                                    "refs": [{"siman": 198, "seif": None}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["topics"], ["zochalin"])
        self.assertFalse(self.client.get("/api/questions?topic=sheuvin").json())

        # export includes the Q&A
        r = self.client.get("/api/export?fmt=md")
        self.assertIn(FAKE_ANSWER, r.text)

        # full-text search over the log
        r = self.client.get("/api/questions", params={"q": "תשובה"})
        self.assertTrue(r.json())

        # delete
        r = self.client.delete(f"/api/questions/{qid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/questions").json(), [])

    def test_browse(self):
        r = self.client.get("/api/texts?siman=198")
        self.assertEqual(len(r.json()), 1)
        r = self.client.get("/api/texts", params={"q": "חציצה"})
        self.assertEqual(r.json()[0]["ref"], "Shulchan Aruch YD 198:1")


if __name__ == "__main__":
    unittest.main()
