"""Capture caméra dans un thread."""
import threading
import time

import cv2


class LatestFrame:
    """Lit la caméra dans un thread et ne garde que la dernière image
    (évite l'accumulation de retard dans le buffer)."""

    def __init__(self, index, width, height, fps):
        self.cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise SystemExit("Caméra inaccessible. Autorise la caméra pour ton Terminal dans "
                             "Réglages Système > Confidentialité et sécurité > Caméra.")
        self.frame, self.stamp, self._seen, self.ts = None, 0, 0, 0.0
        self._cv = threading.Condition()
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self._running:
            ok, f = self.cap.read()
            if ok:
                with self._cv:
                    self.frame, self.stamp, self.ts = f, self.stamp + 1, time.perf_counter()
                    self._cv.notify_all()

    def read(self, timeout=1.0):
        with self._cv:
            self._cv.wait_for(lambda: self.stamp != self._seen, timeout)
            self._seen = self.stamp
            return self.frame, self.ts

    def close(self):
        self._running = False
        self.cap.release()
