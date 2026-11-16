import os
import sys
import unittest
from types import SimpleNamespace as P

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gestures import Hysteresis, analyze  # noqa: E402
from one_euro import OneEuro  # noqa: E402


def hand(thumb=(0.4, 0.5), index_tip=(0.5, 0.2), middle_tip=(0.55, 0.15),
         ring_tip=(0.6, 0.2), pinky_tip=(0.65, 0.3)):
    """Main synthétique : poignet en bas (0.5, 0.9), doigts tendus vers le haut par défaut."""
    lm = [P(x=0.5, y=0.9) for _ in range(21)]
    pts = {0: (0.5, 0.9), 4: thumb, 5: (0.45, 0.6), 6: (0.46, 0.5), 8: index_tip,
           9: (0.5, 0.6), 10: (0.52, 0.5), 12: middle_tip, 14: (0.58, 0.52), 16: ring_tip,
           17: (0.62, 0.6), 18: (0.63, 0.55), 20: pinky_tip}
    for i, (x, y) in pts.items():
        lm[i] = P(x=x, y=y)
    return lm


class TestGestures(unittest.TestCase):
    def test_open_hand(self):
        s = analyze(hand())
        self.assertTrue(s.index_ext and s.middle_ext and s.open_hand)
        self.assertFalse(s.two_fingers)
        self.assertGreater(s.curl_max, 1.0)

    def test_two_fingers(self):
        s = analyze(hand(ring_tip=(0.58, 0.62), pinky_tip=(0.62, 0.65)))
        self.assertTrue(s.two_fingers)
        self.assertFalse(s.open_hand)

    def test_fist(self):
        s = analyze(hand(index_tip=(0.47, 0.68), middle_tip=(0.5, 0.68),
                         ring_tip=(0.55, 0.68), pinky_tip=(0.58, 0.68)))
        self.assertLess(s.curl_max, 0.82)   # sous fist_on calibré

    def test_pinch_distance(self):
        near = analyze(hand(thumb=(0.5, 0.22))).pinch_index
        far = analyze(hand()).pinch_index
        self.assertLess(near, 0.1)
        self.assertGreater(far, near)

    def test_scale_invariant(self):
        a = analyze(hand())
        big = hand()
        for p in big:
            p.x, p.y = 0.5 + (p.x - 0.5) * 0.5, 0.9 + (p.y - 0.9) * 0.5
        b = analyze(big)
        self.assertAlmostEqual(a.pinch_index, b.pinch_index, places=6)
        self.assertAlmostEqual(a.curl_max, b.curl_max, places=6)


class TestHysteresis(unittest.TestCase):
    def test_no_flicker(self):
        h = Hysteresis(0.3, 0.5)
        self.assertFalse(h.update(0.4))   # entre les seuils : reste off
        self.assertTrue(h.update(0.2))
        self.assertTrue(h.update(0.4))    # entre les seuils : reste on
        self.assertFalse(h.update(0.6))


class TestOneEuro(unittest.TestCase):
    def test_constant_signal(self):
        f = OneEuro(1.0, 5.0)
        out = [f(0.5, i / 30) for i in range(30)]
        self.assertAlmostEqual(out[-1], 0.5, places=6)

    def test_reset(self):
        f = OneEuro(1.0, 5.0)
        f(0.1, 0.0); f(0.1, 0.03)
        f.reset()
        self.assertAlmostEqual(f(0.9, 1.0), 0.9, places=6)


if __name__ == "__main__":
    unittest.main()
