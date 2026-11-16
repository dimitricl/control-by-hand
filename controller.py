"""Machine à états des gestes : traduit l'état de la main (HandState) en actions souris.

Aucune dépendance caméra/affichage : testable avec un faux `mouse`.
États : CURSEUR (défaut) · CLIC / GLISSER (pincement) · PAUSE (poing, + clic droit avec le pouce)
· SCROLL (index + majeur) · aucune main / désactivé.
"""
import math
from collections import deque
from dataclasses import dataclass, fields

from gestures import Hysteresis
from one_euro import OneEuro


@dataclass
class ControlConfig:
    zone: tuple = (0.17, 0.25, 0.83, 0.80)
    min_cutoff: float = 1.3
    beta: float = 12.0
    pinch_on: float = 0.28
    pinch_off: float = 0.45
    thumb_on: float = 0.85
    thumb_off: float = 0.65
    drag_px: float = 30
    scroll_speed: float = 14000
    scroll_dead: float = 0.03
    scroll_max: float = 3500          # px/s
    scroll_miss_max: int = 8          # images de tolérance (~250 ms) avant de quitter le scroll
    fist_on: float = 1.35
    fist_off: float = 1.65
    fist_frames: int = 4              # images consécutives pour confirmer chaque geste
    pinch_frames: int = 3
    thumb_frames: int = 3
    rewind: float = 0.08              # s : on revient à la position d'avant le geste
    lost_after: float = 0.4           # s sans main avant de tout relâcher

    @classmethod
    def from_namespace(cls, ns):
        return cls(**{f.name: getattr(ns, f.name) for f in fields(cls) if hasattr(ns, f.name)})


class GestureController:
    def __init__(self, cfg, mouse):
        self.cfg, self.mouse = cfg, mouse
        self.fx = OneEuro(cfg.min_cutoff, cfg.beta)
        self.fy = OneEuro(cfg.min_cutoff, cfg.beta)
        self.fs = OneEuro(1.0, 5.0)                 # filtre du scroll
        self.left_pinch = Hysteresis(cfg.pinch_on, cfg.pinch_off)
        self.hist = deque(maxlen=60)                # (t, x, y) positions filtrées récentes
        self.status, self.thumb_dbg = "aucune main", None
        self.hand_present, self.last_seen = False, 0.0
        self.fist = False                           # poing confirmé (pause)
        self.fist_n = self.pinch_n = self.thumb_n = 0
        self.thumb_armed = False                    # clic droit actif seulement après pouce replié
        self.flash_until = 0.0
        self.down_pos, self.drag_started = None, False
        self.off_x = self.off_y = 0.0               # décalage : le curseur reprend où il était
        self.need_rebase = self.prev_scroll = False
        self.last_scroll_y, self.scroll_acc, self.scroll_t = None, 0.0, 0.0
        self.scroll_on, self.scroll_miss = False, 0

    # --- utilitaires ---
    def _past(self, t, dt):
        """Position filtrée d'il y a dt secondes (avant que le geste ne perturbe la main)."""
        for ts, x, y in reversed(self.hist):
            if ts <= t - dt:
                return x, y
        return (self.hist[0][1], self.hist[0][2]) if self.hist else None

    def _rewind(self, t, dt):
        r, m = self._past(t, dt), self.mouse
        if r and m.pos and abs(r[0] - m.pos[0]) + abs(r[1] - m.pos[1]) < 60:
            m.snap(*r)

    def _reset_filters(self):
        self.fx.reset(); self.fy.reset()

    def lose_hand(self):
        self.mouse.release_all()
        self.left_pinch.state = False
        self.fist, self.fist_n, self.pinch_n, self.thumb_n = False, 0, 0, 0
        self.scroll_on = self.thumb_armed = False
        self.last_scroll_y = None
        self.need_rebase = True
        self.hist.clear()
        self._reset_filters()

    # --- entrées de la boucle principale (une par image) ---
    def on_disabled(self):
        self.thumb_dbg = None
        if self.hand_present:
            self.lose_hand()
            self.hand_present = False
        self.status = "DESACTIVE (Ctrl+Opt+Cmd+Espace)"

    def on_no_hand(self, t):
        self.thumb_dbg = None
        if self.hand_present and t - self.last_seen > self.cfg.lost_after:
            self.lose_hand()
            self.hand_present = False
            self.status = "aucune main"
        elif not self.hand_present:
            self.status = "aucune main"

    def on_hand(self, t, s):
        a, m = self.cfg, self.mouse
        self.thumb_dbg = None
        self.hand_present, self.last_seen = True, t

        # poing : hystérésis + confirmation ; il a priorité sur les clics
        fist_like = s.curl_max < (a.fist_off if self.fist else a.fist_on)
        self.fist_n = self.fist_n + 1 if fist_like else 0
        if not self.fist and self.fist_n >= a.fist_frames:
            self.fist = True
            # le poing se ferme en passant par un faux pincement : on annule tout
            if m.dragging:
                m.mouse_up()
            self.left_pinch.state = False
            self.thumb_armed, self.thumb_n = False, 0
            self._rewind(t, a.rewind + 0.1)
        elif self.fist and not fist_like:
            self.fist = False
            self._reset_filters()
            self.need_rebase = True

        # clic gauche : pincement pouce-index, valide si l'index n'est pas replié en poing
        pinch_ok = (not self.fist) and (not fist_like) and s.index_curl > a.fist_on
        raw_l = pinch_ok and s.pinch_index < (a.pinch_off if self.left_pinch.state else a.pinch_on)
        self.pinch_n = self.pinch_n + 1 if raw_l else 0
        pending = 0 < self.pinch_n < a.pinch_frames and not self.left_pinch.state

        # scroll : on entre avec index+majeur seuls tendus, on reste tant que les deux le sont
        # (tolérance), indépendamment de la position du pouce
        if self.fist:
            self.scroll_on = False
        elif self.scroll_on:
            self.scroll_miss = 0 if (s.index_ext and s.middle_ext and not s.open_hand) else self.scroll_miss + 1
            self.scroll_on = self.scroll_miss <= a.scroll_miss_max
        elif s.two_fingers and not raw_l:
            self.scroll_on, self.scroll_miss = True, 0
        if not self.scroll_on:
            self.last_scroll_y = None
        if self.prev_scroll and not self.scroll_on:
            self._reset_filters()
            self.need_rebase = True
        self.prev_scroll = self.scroll_on

        if self.fist:
            self._pause(t, s)
        elif self.scroll_on:
            self._scroll(t, s)
        else:
            self._cursor(t, s, fist_like, pending, raw_l)

    # --- états ---
    def _pause(self, t, s):
        a = self.cfg
        self.status = "PAUSE (poing)"
        self.thumb_dbg = s.thumb_ext
        # clic droit : déplier le pouce depuis le poing (curseur déjà gelé = clic précis)
        if s.thumb_ext < a.thumb_off:
            self.thumb_armed, self.thumb_n = True, 0
        elif self.thumb_armed and s.thumb_ext > a.thumb_on:
            self.thumb_n += 1
            if self.thumb_n >= a.thumb_frames:
                self.mouse.mouse_down(right=True); self.mouse.mouse_up(right=True)
                self.thumb_armed, self.thumb_n, self.flash_until = False, 0, t + 0.6
        else:
            self.thumb_n = 0
        if t < self.flash_until:
            self.status = "CLIC DROIT"

    def _scroll(self, t, s):
        a = self.cfg
        self.status = "SCROLL"
        if self.last_scroll_y is None:               # début du scroll : point neutre = ici
            self.fs.reset()
            self.last_scroll_y, self.scroll_acc, self.scroll_t = self.fs(s.anchor[1], t), 0.0, t
        y = self.fs(s.anchor[1], t)
        d = y - self.last_scroll_y                   # écart depuis le point neutre
        mag = max(abs(d) - a.scroll_dead, 0.0)
        v = min(mag * a.scroll_speed, a.scroll_max) * (1 if d > 0 else -1)   # px/s
        self.scroll_acc += v * (t - self.scroll_t); self.scroll_t = t
        whole = int(self.scroll_acc); self.scroll_acc -= whole
        self.mouse.scroll(whole)

    def _cursor(self, t, s, fist_like, pending, raw_l):
        a, m = self.cfg, self.mouse
        z0x, z0y, z1x, z1y = a.zone
        self.status = "CURSEUR"
        nx = (s.anchor[0] - z0x) / (z1x - z0x)
        ny = (s.anchor[1] - z0y) / (z1y - z0y)
        nx, ny = min(max(nx, 0), 1), min(max(ny, 0), 1)
        rx, ry = self.fx(nx, t) * m.w, self.fy(ny, t) * m.h
        if self.need_rebase and m.pos:               # le curseur reste où il est, la main repart d'ici
            self.off_x, self.off_y = m.pos[0] - rx, m.pos[1] - ry
            self.need_rebase = False
            self.hist.clear()
        px = min(max(rx + self.off_x, 0), m.w - 1)
        py = min(max(ry + self.off_y, 0), m.h - 1)
        self.off_x, self.off_y = px - rx, py - ry    # contre le bord, le décalage suit : pas de zone morte
        self.hist.append((t, px, py))
        # seuil de glissement : tant qu'on pince et qu'on bouge peu, le curseur reste figé
        # (clic précis, pas de sélection de texte accidentelle)
        if m.dragging and not self.drag_started and self.down_pos:
            if math.hypot(px - self.down_pos[0], py - self.down_pos[1]) > a.drag_px:
                self.drag_started = True
            else:
                px, py = self.down_pos
        # curseur gelé tant qu'un geste est en train de se former
        if not pending and not fist_like:
            m.set_target(px, py)

        want_left = self.pinch_n >= a.pinch_frames or (self.left_pinch.state and raw_l)
        if want_left and not m.dragging:
            self._rewind(t, a.rewind)                # cliquer là où on visait AVANT de pincer
            self.left_pinch.state = True
            m.mouse_down()
            self.down_pos, self.drag_started = m.pos, False
        elif not want_left and m.dragging:
            self.left_pinch.state = False
            m.mouse_up()
        if m.dragging:
            self.status = "CLIC / GLISSER"
