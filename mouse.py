"""Contrôle de la souris macOS via Quartz + thread de sortie haute fréquence.

La caméra fournit ~30 positions/s, ce qui paraît saccadé. Un thread à 120 Hz
rapproche en douceur le curseur de la dernière cible (lissage exponentiel court
avec léger extrapolation), pour un rendu fluide sans latence perceptible.
"""
import threading
import time

from Quartz import (
    CGEventCreateMouseEvent, CGEventCreateScrollWheelEvent, CGEventPost,
    CGDisplayBounds, CGMainDisplayID, CGEventCreate, CGEventGetLocation, kCGHIDEventTap, kCGEventMouseMoved,
    kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGEventLeftMouseDragged,
    kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonLeft,
    kCGMouseButtonRight, kCGScrollEventUnitPixel,
)


def screen_size():
    b = CGDisplayBounds(CGMainDisplayID())
    return b.size.width, b.size.height


def _post(kind, x, y, button=kCGMouseButtonLeft):
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kind, (x, y), button))


class Mouse:
    def __init__(self, rate_hz=120, smooth_tau=0.015, lookahead=0.012, dry_run=False, max_hold=60.0):
        self.w, self.h = screen_size()
        self.rate = rate_hz
        self.tau = smooth_tau        # constante de temps du lissage de sortie (s)
        self.lookahead = lookahead   # extrapolation selon la vitesse (s)
        self.dry_run = dry_run
        self.enabled = True          # coupe-circuit : False = plus aucun événement émis
        self.max_hold = max_hold     # s : un clic maintenu plus longtemps est relâché d'office
        self._down_t = 0.0
        self.target = None
        self.vel = (0.0, 0.0)
        self.pos = None
        self.dragging = False
        self._lock = threading.Lock()
        self._running = True
        self._last_target_t = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # --- appelé par la boucle caméra ---
    def set_target(self, x, y):
        x = min(max(x, 0), self.w - 1)
        y = min(max(y, 0), self.h - 1)
        now = time.perf_counter()
        with self._lock:
            if self.target is not None and self._last_target_t:
                dt = max(now - self._last_target_t, 1e-3)
                vx, vy = (x - self.target[0]) / dt, (y - self.target[1]) / dt
                self.vel = (self.vel[0] * 0.6 + vx * 0.4, self.vel[1] * 0.6 + vy * 0.4)
            self.target = (x, y)
            self._last_target_t = now
            if self.pos is None:
                self.pos = (x, y)

    def snap(self, x, y):
        """Place immédiatement le curseur (annule la dérive pendant un geste)."""
        x = min(max(x, 0), self.w - 1); y = min(max(y, 0), self.h - 1)
        with self._lock:
            self.target = self.pos = (x, y)
            self.vel = (0.0, 0.0)
            self._last_target_t = time.perf_counter()
        if not self.dry_run and self.enabled:
            _post(kCGEventLeftMouseDragged if self.dragging else kCGEventMouseMoved, x, y)

    def set_enabled(self, on):
        """Active/désactive l'émission d'événements. À la désactivation, relâche tout bouton ;
        à la réactivation, repart de la position réelle du curseur."""
        if on == self.enabled:
            return
        if not on:
            self.release_all()
            self.enabled = False
        else:
            if not self.dry_run:
                loc = CGEventGetLocation(CGEventCreate(None))
                with self._lock:
                    self.target = self.pos = (loc.x, loc.y)
                    self.vel = (0.0, 0.0)
            self.enabled = True

    def mouse_down(self, right=False):
        if self.pos is None or self.dry_run or not self.enabled:
            return
        kind = kCGEventRightMouseDown if right else kCGEventLeftMouseDown
        _post(kind, *self.pos, kCGMouseButtonRight if right else kCGMouseButtonLeft)
        self.dragging = not right
        if not right:
            self._down_t = time.perf_counter()

    def mouse_up(self, right=False):
        if self.pos is None or self.dry_run:
            return
        kind = kCGEventRightMouseUp if right else kCGEventLeftMouseUp
        _post(kind, *self.pos, kCGMouseButtonRight if right else kCGMouseButtonLeft)
        if not right:
            self.dragging = False

    def scroll(self, dy_pixels):
        if self.dry_run or not self.enabled or int(dy_pixels) == 0:
            return
        CGEventPost(kCGHIDEventTap, CGEventCreateScrollWheelEvent(
            None, kCGScrollEventUnitPixel, 1, int(dy_pixels)))

    def release_all(self):
        if self.dragging:
            self.mouse_up()

    def stop(self):
        self._running = False
        self.release_all()

    # --- thread de sortie ---
    def _loop(self):
        dt = 1.0 / self.rate
        last = time.perf_counter()
        while self._running:
            time.sleep(dt)
            now = time.perf_counter()
            step, last = now - last, now
            if self.dragging and now - self._down_t > self.max_hold:
                self.mouse_up()          # garde-fou : clic coincé
            with self._lock:
                if self.target is None or self.pos is None:
                    continue
                # Une cible "périmée" (>100 ms) ne doit pas être extrapolée.
                fresh = self._last_target_t is not None and (now - self._last_target_t) < 0.1
                lx = self.vel[0] * self.lookahead if fresh else 0
                ly = self.vel[1] * self.lookahead if fresh else 0
                tx, ty = self.target[0] + lx, self.target[1] + ly
                a = step / (self.tau + step)
                nx = self.pos[0] + (tx - self.pos[0]) * a
                ny = self.pos[1] + (ty - self.pos[1]) * a
                nx = min(max(nx, 0), self.w - 1)
                ny = min(max(ny, 0), self.h - 1)
                moved = abs(nx - self.pos[0]) > 0.05 or abs(ny - self.pos[1]) > 0.05
                self.pos = (nx, ny)
            if moved and not self.dry_run and self.enabled:
                _post(kCGEventLeftMouseDragged if self.dragging else kCGEventMouseMoved, nx, ny)
