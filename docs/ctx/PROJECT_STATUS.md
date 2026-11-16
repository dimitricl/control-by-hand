# PROJECT_STATUS
Dernière mise à jour : 2026-11-16

## État actuel
- Dépôt git local + GitHub public : https://github.com/dimitricl/control-by-hand (branche main, poussée à 84cea9d).
- 24 tests unitaires passent (gestures, one_euro, mouse/coupe-circuit, controller).
- Test réel par l'utilisateur après les derniers correctifs : curseur, clic et scroll « beaucoup mieux ».

## Dernier travail (session du 2026-11-16)
- Analyse + git init, requirements complets, README, calibration robuste, module camera.py, tests.
- Coupe-circuit (raccourci global, Espace dans l'aperçu, relâche auto des clics coincés).
- Refactor de main() -> controller.py (GestureController).
- `--debug` : debug.log par image (statut, doigts, positions, offsets, taille écran).
- Bugs corrigés grâce à debug.log :
  - curseur bloqué en vertical : décalage post-poing + main au bas de la zone (la main est souvent à y≈0,80-0,85 de l'image) ;
  - scroll vers le haut coupé : annulaire/auriculaire qui se déplient comptaient comme échec ;
  - curseur qui sautait à l'entrée du scroll : gel pendant la formation + retour à la position d'avant (0,3 s).

## Prochaine étape
- Multi-écran : l'utilisateur fait souvent de l'AirPlay vers un 27" ; le contrôle est limité à l'écran principal.
- Exposer en options CLI les seuils encore en dur dans ControlConfig (images de confirmation, edge_gain, scroll_*).

## À vérifier  (hypothèses, jamais des faits)
- [?] Taille d'écran lue une seule fois au démarrage : un changement d'AirPlay/résolution en cours de route pourrait fausser le mapping (debug.log montrait des tailles identiques, donc non à l'origine des bugs vus).
- [?] Zone active trop haute pour cet utilisateur : essayer `--zone 0.17 0.30 0.83 0.90`.
- [?] `fist_on` calibré (0.82) réutilisé comme seuil d'index replié dans le pincement (controller.py, `pinch_ok`) : couplage douteux, non touché.
- [?] mouse.py : clics émis à la position lissée, accès à `pos` sans verrou, pas de `join` du thread à l'arrêt.
