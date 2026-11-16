#!/usr/bin/env python3
"""Contrôler le curseur du Mac avec une main, via la caméra.

Gestes (main droite ou gauche) :
  - Main ouverte, déplacer      -> déplace le curseur
  - Pincer pouce + index        -> clic gauche (maintenir = glisser-déposer)
  - Poing fermé puis pouce déplié -> clic droit (le curseur est déjà gelé)
  - Index + majeur tendus       -> scroll continu (main au-dessus/en dessous du point de départ)
  - Poing fermé                 -> pause : repositionne ta main au centre, rouvre-la, le curseur
                                   repart d'où il était (comme soulever une souris)
  - Main hors caméra            -> pause automatique
Aperçu : q/Échap quitte ; 1/2 = plus/moins de lissage ; 3/4 = moins/plus de réactivité.
"""
import argparse
import math
import json
import os
from collections import deque
import threading
import time

import cv2
import mediapipe as mp

from camera import LatestFrame
from gestures import Hysteresis, analyze
from mouse import Mouse
from one_euro import OneEuro


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--zone", type=float, nargs=4, default=[0.17, 0.25, 0.83, 0.80],
                   metavar=("X0", "Y0", "X1", "Y1"),
                   help="zone active de la caméra (0-1). Plus petite = moins de mouvement requis.")
    p.add_argument("--min-cutoff", type=float, default=1.3,
                   help="↓ plus lisse/précis à basse vitesse (défaut 1.3)")
    p.add_argument("--beta", type=float, default=12.0,
                   help="↑ moins de latence en mouvement rapide (défaut 12)")
    p.add_argument("--pinch-on", type=float, default=0.28)
    p.add_argument("--pinch-off", type=float, default=0.45)
    p.add_argument("--thumb-on", type=float, default=0.85, help="pouce déplié depuis le poing -> clic droit")
    p.add_argument("--thumb-off", type=float, default=0.65, help="pouce replié (réarme le clic droit)")
    p.add_argument("--drag-px", type=float, default=30, help="le curseur reste figé tant qu'on pince et qu'on bouge moins que ça")
    p.add_argument("--scroll-speed", type=float, default=14000, help="px/s par unité d'écart de la main")
    p.add_argument("--scroll-dead", type=float, default=0.03, help="zone morte autour du point de départ")
    p.add_argument("--fist-on", type=float, default=1.35, help="courbure sous laquelle la main est un poing")
    p.add_argument("--fist-off", type=float, default=1.65, help="courbure au-dessus de laquelle le poing s'ouvre")
    p.add_argument("--fast", action="store_true", help="modèle MediaPipe léger : moins de latence, un peu moins précis")
    p.add_argument("--dry-run", action="store_true", help="n'envoie aucun événement souris (réglage)")
    p.add_argument("--no-preview", action="store_true")
    # calibration.json (produit par calibrate.py) remplace les valeurs par défaut
    cal_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
    if os.path.exists(cal_path):
        try:
            with open(cal_path) as f:
                cal = json.load(f)
            keys = ("pinch_on", "pinch_off", "thumb_on", "thumb_off", "fist_on", "fist_off", "min_cutoff", "beta")
            p.set_defaults(**{k: float(v) for k, v in cal.items() if k in keys})
            print(f"Calibration chargée : {cal}")
        except (OSError, ValueError, TypeError, AttributeError) as e:
            print(f"Calibration ignorée ({cal_path} illisible : {e}) ; valeurs par défaut utilisées.")
    a = p.parse_args()

    cam = LatestFrame(a.camera, a.width, a.height, a.fps)
    mouse = Mouse(dry_run=a.dry_run)
    fx = OneEuro(a.min_cutoff, a.beta)
    fy = OneEuro(a.min_cutoff, a.beta)
    left_pinch = Hysteresis(a.pinch_on, a.pinch_off)
    z0x, z0y, z1x, z1y = a.zone

    hands = mp.solutions.hands.Hands(
        max_num_hands=1, model_complexity=0 if a.fast else 1,
        min_detection_confidence=0.6, min_tracking_confidence=0.5)
    draw = mp.solutions.drawing_utils

    last_scroll_y = None
    scroll_acc, scroll_t = 0.0, 0.0
    scroll_on, scroll_miss = False, 0
    fs = OneEuro(1.0, 5.0)
    fps_t, fps_n, fps = time.perf_counter(), 0, 0.0
    status = "aucune main"
    hist = deque(maxlen=60)          # (t, x, y) positions filtrées récentes
    fist = False                     # poing confirmé (pause)
    fist_n = pinch_n = thumb_n = 0   # compteurs de confirmation (images consécutives)
    thumb_armed = False              # le clic droit n'est actif qu'après avoir vu le pouce replié
    flash_until = 0.0
    down_pos, drag_started = None, False
    off_x = off_y = 0.0              # décalage écran : le curseur reprend où il était après une pause
    need_rebase, prev_scroll = False, False
    hand_present, last_seen, edge_warn = False, 0.0, False
    FIST_FRAMES, PINCH_FRAMES, THUMB_FRAMES = 4, 3, 3
    REWIND = 0.08                    # s : on revient à la position d'avant le geste

    def past(t, dt):
        """Position filtrée d'il y a dt secondes (avant que le geste ne perturbe la main)."""
        for ts, x, y in reversed(hist):
            if ts <= t - dt:
                return x, y
        return (hist[0][1], hist[0][2]) if hist else None

    def rewind(t, dt):
        r = past(t, dt)
        if r and mouse.pos and abs(r[0] - mouse.pos[0]) + abs(r[1] - mouse.pos[1]) < 60:
            mouse.snap(*r)

    def lose_hand():
        nonlocal last_scroll_y, fist, fist_n, pinch_n, thumb_n, scroll_on, thumb_armed, need_rebase
        mouse.release_all()
        left_pinch.state = False
        fist, fist_n, pinch_n, thumb_n = False, 0, 0, 0
        scroll_on = thumb_armed = False
        last_scroll_y = None
        need_rebase = True
        hist.clear()
        fx.reset(); fy.reset()

    print("Prêt. Ctrl+C ou q pour quitter." + ("  [DRY-RUN]" if a.dry_run else ""))
    try:
        while True:
            frame, t = cam.read()
            if frame is None:
                continue
            frame = cv2.flip(frame, 1)  # effet miroir : droite = droite
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = hands.process(rgb)

            edge_warn, thumb_dbg = False, None
            if not res.multi_hand_landmarks:
                if hand_present and t - last_seen > 0.4:
                    lose_hand()
                    hand_present = False
                    status = "aucune main"
                elif not hand_present:
                    status = "aucune main"
            else:
                hand_present, last_seen = True, t
                lm_obj = res.multi_hand_landmarks[0]
                edge_warn = any(l.x < 0.02 or l.x > 0.98 or l.y < 0.02 or l.y > 0.98
                                for l in lm_obj.landmark)
                s = analyze(lm_obj.landmark)

                # --- poing : hystérésis + confirmation ; il a priorité sur les clics ---
                fist_like = s.curl_max < (a.fist_off if fist else a.fist_on)
                fist_n = fist_n + 1 if fist_like else 0
                if not fist and fist_n >= FIST_FRAMES:
                    fist = True
                    # le poing se ferme en passant par un faux pincement : on annule tout
                    if mouse.dragging:
                        mouse.mouse_up()
                    left_pinch.state = False
                    thumb_armed, thumb_n = False, 0
                    rewind(t, REWIND + 0.1)
                elif fist and not fist_like:
                    fist = False
                    fx.reset(); fy.reset()
                    need_rebase = True

                # clic gauche : pincement pouce-index, valide si l'index n'est pas replié en poing
                pinch_ok = (not fist) and (not fist_like) and s.index_curl > a.fist_on
                raw_l = pinch_ok and s.pinch_index < (a.pinch_off if left_pinch.state else a.pinch_on)
                pinch_n = pinch_n + 1 if raw_l else 0
                pending = 0 < pinch_n < PINCH_FRAMES and not left_pinch.state

                # scroll : on entre avec index+majeur seuls tendus, on reste tant que les deux
                # le sont (tolérance ~250 ms), indépendamment de la position du pouce
                if fist:
                    scroll_on = False
                elif scroll_on:
                    scroll_miss = 0 if (s.index_ext and s.middle_ext and not s.open_hand) else scroll_miss + 1
                    scroll_on = scroll_miss <= 8
                elif s.two_fingers and not raw_l:
                    scroll_on, scroll_miss = True, 0
                if not scroll_on:
                    last_scroll_y = None
                if prev_scroll and not scroll_on:
                    fx.reset(); fy.reset()
                    need_rebase = True
                prev_scroll = scroll_on

                if fist:
                    status = "PAUSE (poing)"
                    thumb_dbg = s.thumb_ext
                    # clic droit : déplier le pouce depuis le poing (curseur déjà gelé = clic précis)
                    if s.thumb_ext < a.thumb_off:
                        thumb_armed, thumb_n = True, 0
                    elif thumb_armed and s.thumb_ext > a.thumb_on:
                        thumb_n += 1
                        if thumb_n >= THUMB_FRAMES:
                            mouse.mouse_down(right=True); mouse.mouse_up(right=True)
                            thumb_armed, thumb_n, flash_until = False, 0, t + 0.6
                    else:
                        thumb_n = 0
                    if t < flash_until:
                        status = "CLIC DROIT"
                elif scroll_on:
                    status = "SCROLL"
                    if last_scroll_y is None:        # début du scroll : point neutre = ici
                        fs.reset()
                        last_scroll_y, scroll_acc, scroll_t = fs(s.anchor[1], t), 0.0, t
                    y = fs(s.anchor[1], t)
                    d = y - last_scroll_y            # écart depuis le point neutre
                    mag = max(abs(d) - a.scroll_dead, 0.0)
                    v = min(mag * a.scroll_speed, 3500) * (1 if d > 0 else -1)   # px/s
                    scroll_acc += v * (t - scroll_t); scroll_t = t
                    whole = int(scroll_acc); scroll_acc -= whole
                    mouse.scroll(whole)
                else:
                    status = "CURSEUR"
                    nx = (s.anchor[0] - z0x) / (z1x - z0x)
                    ny = (s.anchor[1] - z0y) / (z1y - z0y)
                    nx, ny = min(max(nx, 0), 1), min(max(ny, 0), 1)
                    rx, ry = fx(nx, t) * mouse.w, fy(ny, t) * mouse.h
                    if need_rebase and mouse.pos:     # le curseur reste où il est, la main repart d'ici
                        off_x, off_y = mouse.pos[0] - rx, mouse.pos[1] - ry
                        need_rebase = False
                        hist.clear()
                    px = min(max(rx + off_x, 0), mouse.w - 1)
                    py = min(max(ry + off_y, 0), mouse.h - 1)
                    off_x, off_y = px - rx, py - ry     # contre le bord, le décalage suit : pas de zone morte
                    hist.append((t, px, py))
                    # seuil de glissement : tant qu'on pince et qu'on bouge peu, le curseur reste
                    # figé (clic précis, pas de sélection de texte accidentelle)
                    if mouse.dragging and not drag_started and down_pos:
                        if math.hypot(px - down_pos[0], py - down_pos[1]) > a.drag_px:
                            drag_started = True
                        else:
                            px, py = down_pos
                    # curseur gelé tant qu'un geste est en train de se former
                    if not pending and not fist_like:
                        mouse.set_target(px, py)

                    want_left = pinch_n >= PINCH_FRAMES or (left_pinch.state and raw_l)
                    if want_left and not mouse.dragging:
                        rewind(t, REWIND)             # cliquer là où on visait AVANT de pincer
                        left_pinch.state = True
                        mouse.mouse_down()
                        down_pos, drag_started = mouse.pos, False
                    elif not want_left and mouse.dragging:
                        left_pinch.state = False
                        mouse.mouse_up()
                    if mouse.dragging:
                        status = "CLIC / GLISSER"

                if not a.no_preview:
                    draw.draw_landmarks(frame, lm_obj, mp.solutions.hands.HAND_CONNECTIONS)

            fps_n += 1
            if t - fps_t >= 1.0:
                fps, fps_n, fps_t = fps_n / (t - fps_t), 0, t

            if not a.no_preview:
                h, w = frame.shape[:2]
                zone_col = (0, 140, 255) if edge_warn else (0, 255, 120)
                cv2.rectangle(frame, (int(z0x * w), int(z0y * h)), (int(z1x * w), int(z1y * h)),
                              zone_col, 2)
                if thumb_dbg is not None:
                    ok = "ARME" if thumb_armed else "replie le pouce d'abord"
                    cv2.putText(frame, f"pouce {thumb_dbg:.2f}  (clic droit > {a.thumb_on:.2f}, rearme < {a.thumb_off:.2f})  {ok}",
                                (10, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
                if edge_warn:
                    cv2.putText(frame, "MAIN AU BORD DU CADRE", (10, 52),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, zone_col, 2)
                cv2.putText(frame, f"{status}  {fps:.0f} fps", (10, 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 120), 2)
                cv2.putText(frame, f"lissage {fx.min_cutoff:.2f} (1/2)  reactivite {fx.beta:.1f} (3/4)",
                            (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1)
                cv2.imshow("control-by-hand", frame)
                k = cv2.waitKey(1) & 0xFF
                if k in (ord("q"), 27):
                    break
                # réglage en direct : 1/2 = plus/moins de lissage, 3/4 = moins/plus de réactivité
                if k == ord("1"): fx.min_cutoff = fy.min_cutoff = max(0.3, fx.min_cutoff / 1.15)
                if k == ord("2"): fx.min_cutoff = fy.min_cutoff = fx.min_cutoff * 1.15
                if k == ord("3"): fx.beta = fy.beta = max(0.5, fx.beta / 1.3)
                if k == ord("4"): fx.beta = fy.beta = fx.beta * 1.3
    except KeyboardInterrupt:
        pass
    finally:
        mouse.stop()
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
