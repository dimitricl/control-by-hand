# control-by-hand

Contrôle du curseur macOS avec une main, via la caméra (MediaPipe + OpenCV + Quartz).

## Installation
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

Permissions macOS (Réglages Système > Confidentialité et sécurité) pour le Terminal :
**Caméra** et **Accessibilité** (nécessaire pour émettre les événements souris).

## Utilisation
    python3 main.py --dry-run     # réglage sans envoyer d'événements souris
    python3 main.py               # gestes : voir l'en-tête de main.py
    python3 calibrate.py          # produit calibration.json (chargé automatiquement)

Coupe-circuit : **Ctrl+Option+Cmd+Espace** (global) ou **Espace** dans l'aperçu active/désactive le
contrôle ; le bouton est relâché à la désactivation. Le raccourci global demande « Surveillance de
l'entrée » pour le Terminal. Un clic maintenu plus de 60 s est relâché automatiquement.

Arrêt : `q` / Échap dans l'aperçu, ou Ctrl+C.

## Tests
    python3 -m unittest discover -s tests
