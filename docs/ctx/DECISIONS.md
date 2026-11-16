# DECISIONS
<!-- Plus récent en haut. Ne jamais supprimer : marquer « remplacée par … ». -->

## 2026-11-16 — Logique des gestes dans controller.py
- Décision : extraire la machine à états de main() dans `GestureController` (sans dépendance caméra/Quartz).
- Raison : la tester avec un faux `mouse` ; main() faisait 255 lignes avec une dizaine de `nonlocal`.
- Alternatives écartées : garder main() monolithique et tester à la main uniquement.

## 2026-11-16 — Résorption du décalage post-poing par le mouvement de la main
- Décision : le décalage main/écran n'est réduit que lorsque la main sort de la zone vers l'extérieur (proportionnel au mouvement, `edge_gain`=2), jamais main immobile ; suspendu pendant la formation du geste de scroll.
- Raison : sans résorption, le curseur reste bloqué en vertical (debug.log). Une première version à vitesse constante faisait glisser le curseur tout seul vers le bord, y compris à l'entrée du scroll.
- Alternatives écartées : dérive à vitesse constante (800 px/s) ; mapping par morceaux (gain trop fort près d'un bord).

## 2026-11-16 — Coupe-circuit
- Décision : Ctrl+Option+Cmd+Espace (global, CGEventTap en écoute seule), Espace dans l'aperçu, relâche auto d'un clic maintenu > 60 s.
- Raison : un faux geste ne doit pas pouvoir bloquer la souris ; le raccourci global demande « Surveillance de l'entrée » (message si indisponible).
- Alternatives écartées : geste de désactivation (risque de faux positifs).
