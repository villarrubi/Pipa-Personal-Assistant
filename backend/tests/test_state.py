import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.pipa_core.state import (  # noqa: E402
    MAX_SESSION_IDLE_SECONDS,
    SessionLimitError,
    SessionRegistry,
)


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

    def test_stale_sessions_are_pruned_with_a_bounded_idle_window(self):
        registry = SessionRegistry()
        session = registry.create("waveshare-01")

        self.assertEqual(registry.prune(now=session.last_seen_at + MAX_SESSION_IDLE_SECONDS - 1), ())
        self.assertEqual(
            registry.prune(now=session.last_seen_at + MAX_SESSION_IDLE_SECONDS), (session.session_id,)
        )
        self.assertIsNone(registry.get(session.session_id))


if __name__ == "__main__":
    unittest.main()
