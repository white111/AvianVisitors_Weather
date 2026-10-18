"""Decoder tests for the ThermoPro TX-2 (TP-60S) GPIO receiver."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'avian', 'thermopro'))

from tx2_decode import Tx2Decoder, bits_to_reading  # noqa: E402


def encode(type_nibble, sensor_id, battery, button, channel, temp_c, humidity):
    temp_raw = int(round(temp_c * 10)) & 0xFFF
    value = (type_nibble << 32) | (sensor_id << 24) | (battery << 23) | (button << 22) \
        | ((channel - 1) << 20) | (temp_raw << 8) | humidity
    return [(value >> (35 - i)) & 1 for i in range(36)]


def burst(bits, repeats=7, jitter=0.0, rng=None):
    """(level, duration_us) pairs for a TX-2 burst."""
    rng = rng or random.Random(1)

    def j(us):
        return us * (1 + rng.uniform(-jitter, jitter))

    pairs = []
    for _ in range(repeats):
        for bit in bits:
            pairs.append((1, j(500)))
            pairs.append((0, j(4000 if bit else 2000)))
        pairs.append((1, j(500)))
        pairs.append((0, j(9000)))
    return pairs


def run(pairs, start=0.0):
    readings = []
    decoder = Tx2Decoder(readings.append)
    t = start
    for level, us in pairs:
        t += us / 1e6
        decoder.feed(level, us, t)
    return readings


class Tx2DecodeTest(unittest.TestCase):
    def test_fields(self):
        r = bits_to_reading(encode(9, 0xA7, 1, 0, 2, 21.4, 48))
        self.assertEqual((r.sensor_id, r.channel, r.temp_c, r.humidity, r.battery_flag),
                         (0xA7, 2, 21.4, 48, True))

    def test_negative_temperature_and_no_humidity(self):
        r = bits_to_reading(encode(9, 3, 0, 0, 1, -7.3, 0xCC))
        self.assertEqual(r.temp_c, -7.3)
        self.assertIsNone(r.humidity)

    def test_implausible_values_rejected(self):
        self.assertIsNone(bits_to_reading(encode(9, 3, 0, 0, 1, 20.0, 150)))
        self.assertIsNone(bits_to_reading(encode(9, 3, 0, 0, 1, 99.0, 50)))

    def test_burst_reports_once(self):
        readings = run(burst(encode(5, 0x42, 1, 0, 1, 15.6, 63), jitter=0.15))
        self.assertEqual(len(readings), 1)
        self.assertEqual((readings[0].channel, readings[0].temp_c, readings[0].humidity), (1, 15.6, 63))

    def test_single_frame_needs_confirmation(self):
        self.assertEqual(run(burst(encode(9, 1, 1, 0, 1, 20.0, 50), repeats=1)), [])

    def test_noise_between_bursts(self):
        rng = random.Random(7)
        noise = [(i % 2, rng.uniform(80, 6000)) for i in range(4000)]
        pairs = noise + burst(encode(9, 9, 1, 0, 3, 30.1, 22)) + noise
        readings = run(pairs)
        self.assertEqual([(r.channel, r.temp_c) for r in readings], [(3, 30.1)])

    def test_two_sensors(self):
        pairs = burst(encode(9, 1, 1, 0, 1, 10.0, 70)) + [(0, 2e6)] + burst(encode(9, 2, 1, 0, 2, 22.5, 40))
        self.assertEqual([r.channel for r in run(pairs)], [1, 2])


if __name__ == '__main__':
    unittest.main()
