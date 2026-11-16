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

Arrêt : `q` / Échap dans l'aperçu, ou Ctrl+C.

## Tests
    python3 -m unittest discover -s tests
