"""Tests for turning a rain gauge's running total into rain today."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'avian', 'thermopro'))

from rain_today import RainToday  # noqa: E402

DAY1 = time.mktime((2026, 10, 18, 9, 0, 0, 0, 0, -1))
DAY2 = time.mktime((2026, 10, 19, 9, 0, 0, 0, 0, -1))


class RainTodayTest(unittest.TestCase):
    def test_counts_from_the_first_reading_of_the_day(self):
        rain = RainToday(None)
        self.assertEqual(rain.update('g', 100.0, DAY1), 0.0)
        self.assertEqual(rain.update('g', 102.5, DAY1 + 600), 2.5)
        self.assertEqual(rain.update('g', 103.0, DAY1 + 1200), 3.0)

    def test_new_day_starts_at_zero(self):
        rain = RainToday(None)
        rain.update('g', 100.0, DAY1)
        rain.update('g', 104.0, DAY1 + 600)
        self.assertEqual(rain.update('g', 104.0, DAY2), 0.0)
        self.assertEqual(rain.update('g', 105.2, DAY2 + 60), 1.2)

    def test_gauge_restart_keeps_todays_rain(self):
        rain = RainToday(None)
        rain.update('g', 100.0, DAY1)
        rain.update('g', 103.0, DAY1 + 60)
        self.assertEqual(rain.update('g', 0.0, DAY1 + 120), 3.0)   # new batteries
        self.assertEqual(rain.update('g', 1.0, DAY1 + 180), 4.0)

    def test_survives_a_receiver_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'rain.json')
            first = RainToday(path)
            first.update('g', 50.0, DAY1)
            first.update('g', 52.0, DAY1 + 60)
            self.assertEqual(RainToday(path).update('g', 53.0, DAY1 + 120), 3.0)

    def test_sensors_are_separate(self):
        rain = RainToday(None)
        rain.update('a', 10.0, DAY1)
        rain.update('b', 500.0, DAY1)
        self.assertEqual(rain.update('a', 11.0, DAY1 + 60), 1.0)
        self.assertEqual(rain.update('b', 500.0, DAY1 + 60), 0.0)


if __name__ == '__main__':
    unittest.main()
