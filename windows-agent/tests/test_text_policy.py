import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.text_policy import validate_bounded_text  # noqa: E402


class TextPolicyTests(unittest.TestCase):
    def test_accepts_normal_text_and_line_feed_only_for_messages(self):
        self.assertEqual(validate_bounded_text("Daft Punk", "consulta", 200), "Daft Punk")
        self.assertEqual(
            validate_bounded_text("Hola\nMundo", "mensaje", 32, allow_line_feed=True),
            "Hola\nMundo",
        )

        with self.assertRaises(ValueError):
            validate_bounded_text("Hola\nMundo", "consulta", 32)

    def test_rejects_invisible_and_private_use_characters(self):
        for value in ("a\x00b", "a\u202eb", "a\u200bb", "a\ue000b"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_bounded_text(value, "texto", 32, allow_line_feed=True)

    def test_enforces_utf8_byte_limit(self):
        with self.assertRaises(ValueError):
            validate_bounded_text("😀", "texto", 3)


if __name__ == "__main__":
    unittest.main()
