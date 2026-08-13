import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.pipa_core.state import SessionLimitError, SessionRegistry  # noqa: E402


class SessionRegistryTests(unittest.TestCase):
    def test_sessions_are_bounded_per_device(self):
        registry = SessionRegistry()
        with patch("backend.pipa_core.state.MAX_SESSIONS_PER_DEVICE", 1):
            registry.create("waveshare-01")
            with self.assertRaises(SessionLimitError):
                registry.create("waveshare-01")
            registry.create("phone-main")

    def test_global_session_limit_is_enforced(self):
        registry = SessionRegistry()
        with patch("backend.pipa_core.state.MAX_SESSIONS", 1):
            registry.create("waveshare-01")
            with self.assertRaises(SessionLimitError):
                registry.create("phone-main")


if __name__ == "__main__":
    unittest.main()
