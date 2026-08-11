import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
