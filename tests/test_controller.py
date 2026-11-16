import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controller import ControlConfig, GestureController  # noqa: E402
from gestures import HandState  # noqa: E402


class FakeMouse:
    w, h = 1000, 800

    def __init__(self):
        self.pos, self.dragging, self.calls = None, False, []

    def set_target(self, x, y):
        self.pos = (x, y)

    def snap(self, x, y):
        self.pos = (x, y)

    def mouse_down(self, right=False):
        self.calls.append("rdown" if right else "down")
        self.dragging = not right

    def mouse_up(self, right=False):
        self.calls.append("rup" if right else "up")
        if not right:
            self.dragging = False

    def scroll(self, n):
        if n:
            self.calls.append(("scroll", n))

    def release_all(self):
        if self.dragging:
            self.mouse_up()


def state(anchor=(0.5, 0.5), pinch=1.0, curl=1.8, index_curl=1.8, thumb=0.5,
          index_ext=True, middle_ext=True, open_hand=True, two=False):
    return HandState(anchor=anchor, pinch_index=pinch, pinch_middle=1.0, curl_max=curl,
                     index_curl=index_curl, thumb_ext=thumb, index_ext=index_ext,
                     middle_ext=middle_ext, open_hand=open_hand, two_fingers=two)


OPEN = state()
PINCH = state(pinch=0.1)
FIST = state(curl=0.7, index_curl=0.7, index_ext=False, middle_ext=False, open_hand=False, thumb=0.3)
TWO = state(open_hand=False, two=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.m = FakeMouse()
        self.c = GestureController(ControlConfig(), self.m)
        self.t = 0.0

    def feed(self, s, n=1, dt=1 / 30, **kw):
        for _ in range(n):
            self.t += dt
            self.c.on_hand(self.t, s)


class TestCursorAndClick(Base):
    def test_cursor_moves(self):
        self.feed(OPEN, 3)
        self.assertEqual(self.c.status, "CURSEUR")
        self.assertIsNotNone(self.m.pos)

    def test_pinch_needs_confirmation_frames(self):
        self.feed(OPEN, 3)
        self.feed(PINCH, 2)
        self.assertNotIn("down", self.m.calls)
        self.feed(PINCH, 1)
        self.assertEqual(self.m.calls, ["down"])
        self.assertEqual(self.c.status, "CLIC / GLISSER")

    def test_release_pinch_ends_click(self):
        self.feed(OPEN, 3); self.feed(PINCH, 5)
        self.feed(OPEN, 1)
        self.assertEqual(self.m.calls, ["down", "up"])

    def test_cursor_frozen_while_pinch_forming(self):
        self.feed(OPEN, 3)
        before = self.m.pos
        self.feed(state(anchor=(0.6, 0.6), pinch=0.1), 2)
        self.assertEqual(self.m.pos, before)


class TestFist(Base):
    def test_fist_pauses_and_cancels_drag(self):
        self.feed(OPEN, 3); self.feed(PINCH, 4)
        self.assertTrue(self.m.dragging)
        self.feed(FIST, 4)
        self.assertFalse(self.m.dragging)
        self.assertEqual(self.c.status, "PAUSE (poing)")

    def test_right_click_requires_folded_thumb_first(self):
        self.feed(OPEN, 3); self.feed(replace(FIST, thumb_ext=0.75), 4)   # pouce mi-déplié : pas armé
        self.feed(replace(FIST, thumb_ext=0.95), 5)   # pouce déplié sans réarmement
        self.assertNotIn("rdown", self.m.calls)
        self.feed(FIST, 1)                                             # replié -> armé
        self.feed(replace(FIST, thumb_ext=0.95), 3)
        self.assertEqual(self.m.calls[-2:], ["rdown", "rup"])
        self.assertEqual(self.c.status, "CLIC DROIT")


class TestScroll(Base):
    def test_scroll_direction_and_exit(self):
        self.feed(OPEN, 3)
        self.feed(TWO, 2)
        self.assertEqual(self.c.status, "SCROLL")
        self.feed(state(anchor=(0.5, 0.7), open_hand=False, two=True), 10)
        scrolls = [c[1] for c in self.m.calls if isinstance(c, tuple)]
        self.assertTrue(scrolls and all(n > 0 for n in scrolls))
        self.feed(OPEN, 10)                                            # > tolérance : sortie
        self.assertEqual(self.c.status, "CURSEUR")


class TestHandLoss(Base):
    def test_lost_hand_releases_button_after_delay(self):
        self.feed(OPEN, 3); self.feed(PINCH, 4)
        self.assertTrue(self.m.dragging)
        self.c.on_no_hand(self.t + 0.2)
        self.assertTrue(self.m.dragging)             # brève perte tolérée
        self.c.on_no_hand(self.t + 0.5)
        self.assertFalse(self.m.dragging)
        self.assertEqual(self.c.status, "aucune main")

    def test_disabled_releases(self):
        self.feed(OPEN, 3); self.feed(PINCH, 4)
        self.c.on_disabled()
        self.assertFalse(self.m.dragging)
        self.assertTrue(self.c.status.startswith("DESACTIVE"))


if __name__ == "__main__":
    unittest.main()
