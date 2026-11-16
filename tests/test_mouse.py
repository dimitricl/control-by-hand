import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mouse as mouse_mod  # noqa: E402


class TestKillSwitch(unittest.TestCase):
    def setUp(self):
        self.events = []
        self._orig = mouse_mod._post
        mouse_mod._post = lambda kind, x, y, button=0: self.events.append(kind)

    def tearDown(self):
        mouse_mod._post = self._orig

    def make(self, **kw):
        m = mouse_mod.Mouse(**kw)
        m.set_target(100, 100)
        return m

    def test_disable_releases_button_and_blocks_events(self):
        m = self.make()
        m.mouse_down()
        self.assertTrue(m.dragging)
        m.set_enabled(False)
        self.assertFalse(m.dragging)
        self.assertEqual(self.events[-1], mouse_mod.kCGEventLeftMouseUp)
        n = len(self.events)
        m.mouse_down(); m.scroll(5); m.set_target(300, 300); time.sleep(0.1)
        self.assertEqual(len(self.events), n)
        self.assertFalse(m.dragging)
        m.stop()

    def test_stuck_button_released(self):
        m = self.make(max_hold=0.05)
        m.mouse_down()
        time.sleep(0.2)
        self.assertFalse(m.dragging)
        m.stop()


if __name__ == "__main__":
    unittest.main()
