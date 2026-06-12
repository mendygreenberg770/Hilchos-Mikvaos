import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import llm  # noqa: E402


class TestBackendSelection(unittest.TestCase):
    def test_api_key_wins(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            self.assertEqual(llm.mode(), "api")

    def test_subscription_when_sdk_present_no_key(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        with patch.dict(os.environ, env, clear=True), \
             patch("importlib.util.find_spec", return_value=object()):
            self.assertEqual(llm.mode(), "subscription")

    def test_none_when_nothing_connected(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        with patch.dict(os.environ, env, clear=True), \
             patch("importlib.util.find_spec", return_value=None):
            self.assertEqual(llm.mode(), "none")
            with self.assertRaises(RuntimeError):
                llm.complete(system="s", user="u", model="m")


class TestHelpers(unittest.TestCase):
    def test_subscription_model_mapping(self):
        self.assertEqual(llm._subscription_model("claude-sonnet-4-6"), "sonnet")
        self.assertEqual(llm._subscription_model("claude-opus-4-8"), "opus")
        self.assertEqual(llm._subscription_model("claude-haiku-4-5"), "haiku")

    def test_extract_json(self):
        self.assertEqual(llm.extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(
            llm.extract_json('Here you go:\n```json\n{"topics": ["chatzitza"]}\n```'),
            {"topics": ["chatzitza"]})
        self.assertIsNone(llm.extract_json("no json here"))


if __name__ == "__main__":
    unittest.main()
