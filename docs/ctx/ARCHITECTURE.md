# ARCHITECTURE

## Rôle
Contrôle du curseur macOS (Apple Silicon) avec une main filmée par la caméra : MediaPipe Hands -> gestes -> événements Quartz.

## Composants et flux
- `camera.py` `LatestFrame` : thread de capture, ne garde que la dernière image.
- `gestures.py` `analyze()` : 21 landmarks -> `HandState` (pincement, courbure, doigts tendus), indépendant de l'échelle.
- `controller.py` `GestureController` + `ControlConfig` : machine à états (CURSEUR / CLIC-GLISSER / PAUSE-poing + clic droit pouce / SCROLL / aucune main / désactivé). Sans dépendance caméra ni Quartz : testable avec un faux `mouse`.
- `one_euro.py` : filtre One Euro (lissage adaptatif).
- `mouse.py` `Mouse` : thread de sortie 120 Hz (lissage + extrapolation), `set_enabled` (coupe-circuit), relâche auto d'un clic > 60 s. Écran principal uniquement (`CGMainDisplayID`).
- `killswitch.py` : raccourci global Ctrl+Option+Cmd+Espace (CGEventTap, écoute seule).
- `main.py` : arguments, boucle caméra, aperçu, `--debug` (écrit `debug.log`, ignoré par git).
- `calibrate.py` -> `calibration.json` (chargé par `main.py`, remplace les défauts ; ignoré proprement s'il est illisible).
- Principe clé : après une pause (poing) le curseur repart d'où il était (décalage `off_x/off_y` entre main et écran) ; ce décalage est résorbé seulement quand la main sort de la zone vers l'extérieur (`edge_gain`).

## Commandes (build / test / run)
- test : `python3 -m unittest discover -s tests`  (24 tests, vérifié)
- run : `python3 main.py` ; réglage sans souris : `--dry-run` ; diagnostic : `--debug`
- calibration : `python3 calibrate.py`
