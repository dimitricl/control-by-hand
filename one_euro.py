"""One Euro Filter (Casiez et al., 2012).

Lisse fortement quand la main bouge lentement (précision, pas de tremblement)
et devient très réactif quand elle bouge vite (pas de latence).
"""
import math


class LowPass:
    def __init__(self):
        self.y = None

    def __call__(self, x, alpha):
        self.y = x if self.y is None else alpha * x + (1 - alpha) * self.y
        return self.y


class OneEuro:
    def __init__(self, min_cutoff=1.0, beta=0.02, d_cutoff=1.0):
        self.min_cutoff = min_cutoff  # ↓ = plus lisse à basse vitesse
        self.beta = beta              # ↑ = moins de latence à haute vitesse
        self.d_cutoff = d_cutoff
        self._x = LowPass()
        self._dx = LowPass()
        self._t = None
        self._prev = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.__init__(self.min_cutoff, self.beta, self.d_cutoff)

    def __call__(self, x, t):
        if self._t is None:
            self._t, self._prev = t, x
            return self._x(x, 1.0)
        dt = max(t - self._t, 1e-4)
        dx = (x - self._prev) / dt
        edx = self._dx(dx, self._alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        out = self._x(x, self._alpha(cutoff, dt))
        self._t, self._prev = t, x
        return out
