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
Coupe-circuit : Ctrl+Option+Cmd+Espace (global) ou Espace dans l'aperçu = active/désactive.
Aperçu : q/Échap quitte ; 1/2 = plus/moins de lissage ; 3/4 = moins/plus de réactivité.
"""
import argparse
import json
import os
import time

import cv2
import mediapipe as mp

from camera import LatestFrame
import killswitch
from controller import ControlConfig, GestureController
from gestures import analyze
from mouse import Mouse, screen_size
from one_euro import OneEuro


def show_preview(frame, ctl, a, fps, edge_warn):
    """Dessine l'aperçu et renvoie la touche pressée (0xFF si aucune)."""
    z0x, z0y, z1x, z1y = a.zone
    h, w = frame.shape[:2]
    zone_col = (0, 140, 255) if edge_warn else (0, 255, 120)
    cv2.rectangle(frame, (int(z0x * w), int(z0y * h)), (int(z1x * w), int(z1y * h)), zone_col, 2)
    if ctl.thumb_dbg is not None:
        ok = "ARME" if ctl.thumb_armed else "replie le pouce d'abord"
        cv2.putText(frame, f"pouce {ctl.thumb_dbg:.2f}  (clic droit > {a.thumb_on:.2f}, rearme < {a.thumb_off:.2f})  {ok}",
                    (10, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
    if edge_warn:
        cv2.putText(frame, "MAIN AU BORD DU CADRE", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, zone_col, 2)
    cv2.putText(frame, f"{ctl.status}  {fps:.0f} fps", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 120), 2)
    cv2.putText(frame, f"lissage {ctl.fx.min_cutoff:.2f} (1/2)  reactivite {ctl.fx.beta:.1f} (3/4)",
                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1)
    cv2.imshow("control-by-hand", frame)
    return cv2.waitKey(1) & 0xFF


def tune(ctl, k):
    """Réglage en direct : 1/2 = plus/moins de lissage, 3/4 = moins/plus de réactivité."""
    fx, fy = ctl.fx, ctl.fy
    if k == ord("1"): fx.min_cutoff = fy.min_cutoff = max(0.3, fx.min_cutoff / 1.15)
    if k == ord("2"): fx.min_cutoff = fy.min_cutoff = fx.min_cutoff * 1.15
    if k == ord("3"): fx.beta = fy.beta = max(0.5, fx.beta / 1.3)
    if k == ord("4"): fx.beta = fy.beta = fx.beta * 1.3


def debug_line(t, mouse, ctl, res):
    """Une ligne de diagnostic : état, valeurs internes, écran réel vs écran au démarrage."""
    lw, lh = screen_size()
    lm = res.multi_hand_landmarks[0].landmark if res is not None and res.multi_hand_landmarks else None
    hand = f"mcp5=({lm[5].x:.3f},{lm[5].y:.3f}) mcp9=({lm[9].x:.3f},{lm[9].y:.3f})" if lm else "mains=0"
    d = " ".join(f"{k}={v:.1f}" if abs(v) >= 10 else f"{k}={v:.3f}" for k, v in ctl.dbg.items())
    pos = f"({mouse.pos[0]:.1f},{mouse.pos[1]:.1f})" if mouse.pos else "None"
    tgt = f"({mouse.target[0]:.1f},{mouse.target[1]:.1f})" if mouse.target else "None"
    return (f"{t:.3f} [{ctl.status}] {hand} {d} pos={pos} target={tgt} drag={int(mouse.dragging)} "
            f"fist={int(ctl.fist)} scroll={int(ctl.scroll_on)} rebase={int(ctl.need_rebase)} "
            f"screen={lw:.0f}x{lh:.0f}/{mouse.w:.0f}x{mouse.h:.0f}")


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
    p.add_argument("--debug", action="store_true", help="écrit debug.log (une ligne par image) pour diagnostiquer")
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
    ctl = GestureController(ControlConfig.from_namespace(a), mouse)

    hands = mp.solutions.hands.Hands(
        max_num_hands=1, model_complexity=0 if a.fast else 1,
        min_detection_confidence=0.6, min_tracking_confidence=0.5)
    draw = mp.solutions.drawing_utils
    fps_t, fps_n, fps = time.perf_counter(), 0, 0.0
    dbg_file = None
    if a.debug:
        dbg_file = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log"), "w", buffering=1)
        print(f"Debug : écriture dans debug.log (écran au démarrage {mouse.w:.0f}x{mouse.h:.0f})")

    def toggle():
        mouse.set_enabled(not mouse.enabled)
        print("Contrôle ACTIVÉ" if mouse.enabled else "Contrôle DÉSACTIVÉ (coupe-circuit)")

    if not killswitch.start(toggle):
        print("Raccourci global indisponible (autorise « Surveillance de l'entrée » pour le Terminal) ; "
              "utilise Espace dans l'aperçu ou Ctrl+C.")
    print("Prêt. Ctrl+C ou q pour quitter." + ("  [DRY-RUN]" if a.dry_run else ""))
    try:
        while True:
            frame, t = cam.read()
            if frame is None:
                continue
            frame = cv2.flip(frame, 1)  # effet miroir : droite = droite
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = hands.process(rgb) if mouse.enabled else None

            edge_warn = False
            if not mouse.enabled:
                ctl.on_disabled()
            elif not res.multi_hand_landmarks:
                ctl.on_no_hand(t)
            else:
                lm_obj = res.multi_hand_landmarks[0]
                edge_warn = any(l.x < 0.02 or l.x > 0.98 or l.y < 0.02 or l.y > 0.98
                                for l in lm_obj.landmark)
                ctl.on_hand(t, analyze(lm_obj.landmark))
                if not a.no_preview:
                    draw.draw_landmarks(frame, lm_obj, mp.solutions.hands.HAND_CONNECTIONS)

            if dbg_file:
                dbg_file.write(debug_line(t, mouse, ctl, res if mouse.enabled else None) + "\n")

            fps_n += 1
            if t - fps_t >= 1.0:
                fps, fps_n, fps_t = fps_n / (t - fps_t), 0, t

            if not a.no_preview:
                k = show_preview(frame, ctl, a, fps, edge_warn)
                if k in (ord("q"), 27):
                    break
                if k == ord(" "):
                    toggle()
                tune(ctl, k)
    except KeyboardInterrupt:
        pass
    finally:
        if dbg_file:
            dbg_file.close()
        mouse.stop()
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
