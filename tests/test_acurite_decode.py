"""Decoder tests for AcuRite 592TXR tower sensors on the RXB6 receiver."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'avian', 'thermopro'))

from acurite_decode import AcuriteTowerDecoder, bits_to_reading, message_to_reading  # noqa: E402
from tx2_decode import Tx2Decoder  # noqa: E402


def parity(byte):
    byte &= 0x7F
    return byte | (0x80 if bin(byte).count('1') % 2 else 0)


def message(sensor_id, channel, temp_c, humidity, battery_ok=True):
    channel_bits = {'A': 3, 'B': 2, 'C': 0}[channel]
    raw = int(round(temp_c * 10)) + 1000
    msg = [
        (channel_bits << 6) | ((sensor_id >> 8) & 0x3F),
        sensor_id & 0xFF,
        parity((0x40 if battery_ok else 0) | 0x04),
        parity(humidity),
        parity((raw >> 7) & 0x0F),
        parity(raw & 0x7F),
    ]
    msg.append(sum(msg) & 0xFF)
    return msg


def bits_of(msg):
    return [(byte >> (7 - i)) & 1 for byte in msg for i in range(8)]


def burst(msg, invert=False, jitter=0.15, seed=3):
    rng = random.Random(seed)

    def j(us):
        return us * (1 + rng.uniform(-jitter, jitter))

    bits = bits_of(msg)
    if invert:
        bits = [1 - b for b in bits]
    pairs = []
    for _ in range(3):
        for _ in range(4):
            pairs += [(1, j(600)), (0, j(600))]
        for bit in bits:
            pairs += [(1, j(400)), (0, j(200))] if bit else [(1, j(200)), (0, j(400))]
    pairs.append((0, 20000))
    return pairs


def tx2_burst():
    value = (9 << 32) | (0x42 << 24) | (1 << 23) | (0 << 20) | (156 << 8) | 63
    bits = [(value >> (35 - i)) & 1 for i in range(36)]
    pairs = []
    for _ in range(7):
        for bit in bits:
            pairs += [(1, 500), (0, 4000 if bit else 2000)]
        pairs += [(1, 500), (0, 9000)]
    return pairs


def run(decoder_cls, pairs):
    out = []
    decoder = decoder_cls(out.append)
    t = 0.0
    for level, us in pairs:
        t += us / 1e6
        decoder.feed(level, us, t)
    return out


class AcuriteDecodeTest(unittest.TestCase):
    def test_fields(self):
        r = message_to_reading(message(0x1A2B, 'A', 21.7, 45))
        self.assertEqual((r.sensor_id, r.channel, r.temp_c, r.humidity, r.battery_ok),
                         (0x1A2B, 'A', 21.7, 45, True))

    def test_negative_temperature_channel_c(self):
        r = message_to_reading(message(5, 'C', -12.3, 80, battery_ok=False))
        self.assertEqual((r.channel, r.temp_c, r.battery_ok), ('C', -12.3, False))

    def test_checksum_and_parity_reject(self):
        bad = message(0x1A2B, 'A', 21.7, 45)
        bad[5] ^= 0x01
        self.assertIsNone(message_to_reading(bad))

    def test_either_bit_polarity(self):
        bits = bits_of(message(7, 'B', 18.0, 60))
        self.assertIsNotNone(bits_to_reading(bits))
        self.assertIsNotNone(bits_to_reading([1 - b for b in bits]))

    def test_burst_reports_once(self):
        for invert in (False, True):
            out = run(AcuriteTowerDecoder, burst(message(0x1A2B, 'A', 21.7, 45), invert=invert))
            self.assertEqual([(o.channel, o.temp_c, o.humidity) for o in out], [('A', 21.7, 45)])

    def test_noise_around_a_burst(self):
        rng = random.Random(9)
        noise = [(i % 2, rng.uniform(60, 3000)) for i in range(6000)]
        out = run(AcuriteTowerDecoder, noise + burst(message(77, 'B', 30.0, 20)) + noise)
        self.assertEqual([(o.channel, o.temp_c) for o in out], [('B', 30.0)])

    def test_decoders_ignore_each_other(self):
        self.assertEqual(run(AcuriteTowerDecoder, tx2_burst()), [])
        self.assertEqual(run(Tx2Decoder, burst(message(0x1A2B, 'A', 21.7, 45))), [])
        self.assertEqual(len(run(Tx2Decoder, tx2_burst())), 1)


if __name__ == '__main__':
    unittest.main()
