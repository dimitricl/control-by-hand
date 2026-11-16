"""Analyse des 21 points MediaPipe -> état de la main (indépendant de la distance/rotation)."""
import math
from dataclasses import dataclass

WRIST, THUMB_TIP = 0, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20


def _d(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _extended(lm, pip, tip):
    # Un doigt est tendu si son bout est plus loin du poignet que son articulation PIP.
    return _d(lm[tip], lm[WRIST]) > _d(lm[pip], lm[WRIST]) * 1.08


@dataclass
class HandState:
    anchor: tuple          # point de pointage stable (x, y) normalisé caméra
    pinch_index: float     # distance pouce-index / taille de la main (petit = pincé)
    pinch_middle: float    # distance pouce-majeur / taille de la main
    curl_max: float        # courbure max des 4 doigts (petit = tous repliés = poing)
    index_curl: float      # bout de l'index / taille de la main (grand = tendu)
    thumb_ext: float       # bout du pouce / base de l'index, normalisé (grand = pouce déplié)
    index_ext: bool        # index tendu
    middle_ext: bool       # majeur tendu
    open_hand: bool        # annulaire ET auriculaire tendus (main ouverte -> pas de scroll)
    two_fingers: bool      # index + majeur tendus, annulaire + auriculaire repliés -> scroll


def analyze(lm) -> HandState:
    size = max(_d(lm[WRIST], lm[MIDDLE_MCP]), 1e-6)  # échelle de la main
    # Ancre = entre la base de l'index et du majeur : ne bouge presque pas
    # quand on pince, donc le clic ne décale pas le curseur.
    ax = (lm[INDEX_MCP].x * 0.6 + lm[MIDDLE_MCP].x * 0.4)
    ay = (lm[INDEX_MCP].y * 0.6 + lm[MIDDLE_MCP].y * 0.4)

    idx = _extended(lm, INDEX_PIP, INDEX_TIP)
    mid = _extended(lm, MIDDLE_PIP, MIDDLE_TIP)
    rng = _extended(lm, RING_PIP, RING_TIP)
    pnk = _extended(lm, PINKY_PIP, PINKY_TIP)

    curls = [_d(lm[t], lm[WRIST]) / size for t in (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
    return HandState(
        anchor=(ax, ay),
        pinch_index=_d(lm[THUMB_TIP], lm[INDEX_TIP]) / size,
        pinch_middle=_d(lm[THUMB_TIP], lm[MIDDLE_TIP]) / size,
        curl_max=max(curls),
        index_curl=curls[0],
        thumb_ext=_d(lm[THUMB_TIP], lm[INDEX_MCP]) / size,
        index_ext=idx,
        middle_ext=mid,
        open_hand=rng and pnk,
        two_fingers=idx and mid and not rng and not pnk,
    )


class Hysteresis:
    """Seuil à deux niveaux pour éviter les clics fantômes qui clignotent."""

    def __init__(self, on, off):
        self.on, self.off, self.state = on, off, False

    def update(self, value):
        if not self.state and value < self.on:
            self.state = True
        elif self.state and value > self.off:
            self.state = False
        return self.state
