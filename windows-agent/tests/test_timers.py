import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.timers import TimerManager, TimerNotFoundError  # noqa: E402


class TimerManagerTests(unittest.TestCase):
    def test_timer_can_be_created_and_cancelled(self):
        manager = TimerManager()
        created = manager.create(60, "Prueba")

        self.assertEqual(created["status"], "pending")
        cancelled = manager.cancel(created["timer_id"])
        self.assertEqual(cancelled["status"], "cancelled")

    def test_unknown_timer_is_rejected(self):
        with self.assertRaises(TimerNotFoundError):
            TimerManager().cancel("missing")

    def test_timer_ids_are_bounded_and_route_safe(self):
        with self.assertRaises(ValueError):
            TimerManager().cancel("../system/status")

    def test_active_timers_are_bounded(self):
        manager = TimerManager()
        with patch("tools.timers.MAX_ACTIVE_TIMERS", 1):
            first = manager.create(60, "Primero")
            with self.assertRaises(ValueError):
                manager.create(60, "Segundo")
            manager.cancel(first["timer_id"])
            second = manager.create(60, "Después")
            manager.cancel(second["timer_id"])


if __name__ == "__main__":
    unittest.main()
