from __future__ import annotations

from datetime import datetime, timezone
import unittest

from core.services.schedule_time import compute_next_fire_at


class ScheduleTimeV4Tests(unittest.TestCase):
    def test_daily_schedule_uses_timezone_and_next_day_when_time_passed(self):
        now = datetime(2026, 4, 29, 1, 0, tzinfo=timezone.utc)  # 09:00 Asia/Shanghai

        next_fire = compute_next_fire_at(
            trigger_type="daily",
            trigger_config={"time_of_day": "08:00"},
            timezone_name="Asia/Shanghai",
            after=now,
        )

        self.assertEqual(next_fire, datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc))

    def test_daily_schedule_accepts_common_time_aliases(self):
        now = datetime(2026, 4, 29, 22, 0, tzinfo=timezone.utc)  # 06:00 Asia/Shanghai

        next_fire = compute_next_fire_at(
            trigger_type="daily",
            trigger_config={"type": "daily", "time": "7:00"},
            timezone_name="Asia/Shanghai",
            after=now,
        )

        self.assertEqual(next_fire, datetime(2026, 4, 29, 23, 0, tzinfo=timezone.utc))

    def test_daily_schedule_accepts_hour_minute_aliases(self):
        now = datetime(2026, 4, 29, 22, 0, tzinfo=timezone.utc)  # 06:00 Asia/Shanghai

        next_fire = compute_next_fire_at(
            trigger_type="daily",
            trigger_config={"type": "daily", "hour": 7, "minute": 15},
            timezone_name="Asia/Shanghai",
            after=now,
        )

        self.assertEqual(next_fire, datetime(2026, 4, 29, 23, 15, tzinfo=timezone.utc))

    def test_cron_schedule_finds_next_matching_minute(self):
        now = datetime(2026, 4, 29, 3, 1, tzinfo=timezone.utc)

        next_fire = compute_next_fire_at(
            trigger_type="cron",
            trigger_config={"expression": "*/5 * * * *"},
            timezone_name="UTC",
            after=now,
        )

        self.assertEqual(next_fire, datetime(2026, 4, 29, 3, 5, tzinfo=timezone.utc))

    def test_one_shot_schedule_does_not_repeat_after_fire_time(self):
        now = datetime(2026, 4, 29, 3, 1, tzinfo=timezone.utc)

        next_fire = compute_next_fire_at(
            trigger_type="one_shot",
            trigger_config={"run_at": "2026-04-29T03:00:00Z"},
            timezone_name="UTC",
            after=now,
        )

        self.assertIsNone(next_fire)


if __name__ == "__main__":
    unittest.main()
