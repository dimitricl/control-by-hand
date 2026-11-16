#!/usr/bin/env python3
"""Calibration guidée : mesure TA main et déduit les seuils (poing, pincement, lissage).
Écrit calibration.json, relu automatiquement par main.py.

Lance : python3 calibrate.py   (reste à ta distance habituelle de la caméra)
"""
import json
import os
import time

import cv2
import mediapipe as mp
import numpy as np

from gestures import analyze
from main import LatestFrame

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
PHASES = [
    ("open",      "1/4  MAIN OUVERTE, IMMOBILE (doigts ecartes)"),
    ("pinch",     "2/4  PINCE pouce + INDEX et GARDE (autres doigts tendus)"),
    ("fist",      "3/4  POING FERME, pouce REPLIE sur les doigts"),
    ("fistthumb", "4/4  POING FERME, pouce DEPLIE (comme un 'pouce en l'air')"),
]
READY, HOLD, SETTLE = 2.5, 3.5, 0.8


def main():
    cam = LatestFrame(0, 640, 480, 30)
    hands = mp.solutions.hands.Hands(max_num_hands=1, model_complexity=1,
                                     min_detection_confidence=0.6, min_tracking_confidence=0.6)
    draw = mp.solutions.drawing_utils
    data = {k: [] for k, _ in PHASES}
    for key, title in PHASES:
        t0 = time.perf_counter()
        while (el := time.perf_counter() - t0) < READY + HOLD:
            frame, _ = cam.read()
            if frame is None:
                continue
            frame = cv2.flip(frame, 1)
            res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            seen = bool(res.multi_hand_landmarks)
            if seen:
                lm = res.multi_hand_landmarks[0]
                draw.draw_landmarks(frame, lm, mp.solutions.hands.HAND_CONNECTIONS)
                if el >= READY + SETTLE:
                    s = analyze(lm.landmark)
                    data[key].append((s.curl_max, s.index_curl, s.pinch_index, s.pinch_middle,
                                      s.anchor[0], s.anchor[1], s.thumb_ext))
            phase = "PREPARE-TOI" if el < READY else "MESURE... garde la pose, ne bouge pas"
            col = (0, 200, 255) if el < READY else (0, 255, 120)
            cv2.putText(frame, title, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
            cv2.putText(frame, phase + ("" if seen else "   [main non detectee]"), (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
            cv2.imshow("calibration", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                return
    cam.close()
    cv2.destroyAllWindows()

    A = {k: np.array(v) for k, v in data.items()}
    for k, v in A.items():
        if len(v) < 20:
            raise SystemExit(f"Phase '{k}': main vue trop peu ({len(v)} images). Recommence, main bien visible.")
    pc = lambda x, q: float(np.percentile(x, q))

    # colonnes : 0 curl_max, 1 index_curl, 2 pinch_index, 3 pinch_middle, 4-5 anchor
    open_pinch_idx = pc(A["open"][:, 2], 20)       # écart pouce-index le plus faible main ouverte
    pinched_idx = pc(A["pinch"][:, 2], 75)         # écart le plus grand pendant un vrai pincement
    gap_p = open_pinch_idx - pinched_idx
    pinch_on = pinched_idx + 0.16 * gap_p          # déclenche seulement sur un pincement franc
    pinch_off = pinched_idx + 0.34 * gap_p
    pinch_ref, pinch_open_ref = pinched_idx, open_pinch_idx

    thumb_in = pc(A["fist"][:, 6], 85)             # pouce replié : valeur haute typique
    thumb_out = pc(A["fistthumb"][:, 6], 15)       # pouce déplié : valeur basse typique
    gap_t = thumb_out - thumb_in
    thumb_off = thumb_in + 0.35 * gap_t
    thumb_on = thumb_in + 0.65 * gap_t

    fist_top = pc(A["fist"][:, 0], 80)             # poing le moins serré
    notfist_bottom = min(pc(A["pinch"][:, 1], 10), pc(A["open"][:, 0], 10))
    gap_f = notfist_bottom - fist_top
    fist_on = fist_top + 0.35 * gap_f
    fist_off = fist_top + 0.70 * gap_f

    d = np.diff(A["open"][:, 4:6], axis=0)   # bruit haute fréquence, indépendant de la dérive
    jit = float(np.mean(np.std(d, axis=0)) / np.sqrt(2))
    min_cutoff = 1.0 if jit > 0.004 else 1.3 if jit > 0.0025 else 1.7

    cal = dict(pinch_on=round(pinch_on, 3), pinch_off=round(pinch_off, 3),
               thumb_on=round(thumb_on, 3), thumb_off=round(thumb_off, 3),
               fist_on=round(fist_on, 3), fist_off=round(fist_off, 3),
               min_cutoff=min_cutoff, beta=15.0)
    json.dump(cal, open(OUT, "w"), indent=2)

    json.dump({k: v.tolist() for k, v in A.items()}, open(OUT.replace(".json", "_raw.json"), "w"))
    print("\n=== Distributions (p10 / médiane / p90) ===")
    for k, c, name in (("open", 2, "main ouverte : pouce-index"), ("pinch", 2, "pince index    : pouce-index"),
                       ("fist", 6, "poing pouce replie: ext. pouce"), ("fistthumb", 6, "poing pouce deplie: ext. pouce"),
                       ("pinch", 1, "pince index    : courbure index"),
                       ("fist", 0, "poing          : courbure max")):
        v = A[k][:, c]
        print(f"{name:32s} {pc(v,10):.2f} / {pc(v,50):.2f} / {pc(v,90):.2f}")
    print("\n=== Mesures sur ta main ===")
    print(f"Pincement : main ouverte >= {pinch_open_ref:.2f} | pince <= {pinch_ref:.2f}  (marge {gap_p:.2f})")
    print(f"Poing     : poing <= {fist_top:.2f} | pas poing >= {notfist_bottom:.2f}  (marge {gap_f:.2f})")
    print(f"Tremblement de ta main immobile : {jit*100:.2f}% de l'image (bruit image a image) -> lissage {min_cutoff}")
    if gap_p < 0.25:
        print("! Marge pincement faible : pince franchement pouce/index, ou rapproche-toi de la camera.")
    print(f"Pouce     : replié <= {thumb_in:.2f} | déplié >= {thumb_out:.2f}  (marge {gap_t:.2f})")
    if gap_t < 0.2:
        print("! Marge pouce faible : deplie le pouce franchement (vers le haut ou le cote).")
    if gap_f < 0.25:
        print("! Marge poing faible : ferme le poing franchement (doigts bien replies dans la paume).")
    print(f"\nSauvegarde -> {OUT}\nRelance maintenant : python3 main.py")


if __name__ == "__main__":
    main()
