# UGC Zero Credit — V6 (31 octobre 2026)

## Nouvelles capacités (aucune génération payante)

1. `editorial_quality.py` mesure la part de parole masquée par les plans produit, le nombre de transitions et la présence d'une accroche visible. **Il n'affirme pas mesurer la synchronisation phonétique lèvres/voix.**
2. `auto_edit.py` propose un nouveau JSON non destructif : moins de coupes, b-roll placé près des silences horodatés, limite de parole masquée à 50 %, protection du hook et du final. Il peut éliminer des inserts ; toute proposition doit être revue car le sujet du plan peut ne plus correspondre à la phrase.
3. `visual_assets.py` classe les images/vidéos locales par netteté, exposition et contraste ; signale les doublons possibles par hash perceptuel. **Le classement ne vérifie ni la marque ni les droits.** OpenCV est requis pour cette commande seulement.
4. `review_dashboard.py` génère une page autonome `review_mobile.html` contenant lecteur vidéo, chronologie des inserts, mesures audio et liste de revue manuelle. Sans CDN, requête réseau ni stockage.
5. Nouveau mode `editorial_policy="required"` pour refuser l'export et la prépublication si le montage masque excessivement la présentatrice. `review` conserve la compatibilité V5.
6. Protection supplémentaire : l'export refuse une destination dont la miniature JPEG pourrait écraser une image utilisée comme source.
7. Le rapport `.report.json` contient désormais `editorial_quality`. Le contrôle final `release_gate.py` examine également ce critère.

## Résultats mesurés

Exemple technique V5 : 60,5 % de la durée des mots masquée, 60 transitions/minute, statut WARN.
Exemple technique réorganisé V6 : **23,7 % masqués**, **30 transitions/minute**, statut PASS.

Les pourcentages sont calculés à partir des seuls mots horodatés de l'exemple et d'inserts qui recouvrent tout le cadre ; ce ne sont pas des métriques marketing ou des garanties perceptuelles. L'exemple emploie une séquence synthétique, pas une influenceuse.

Le rendu V6 Full HD de 4,0 secondes a été décodé intégralement, avec H.264 1080×1920 30 fps et AAC. Le contrôle source→sortie du timing audio est PASS. Mesures du mixage : environ −15,3 LUFS et −6,6 dBTP.

V6 : **44 assertions fonctionnelles** passées, plus réexécution des suites antérieures V3, V4 et V5. Aucun téléchargement de poids, aucune génération cloud payante, aucun appel à l'API IA.

## Limites

- Une image produit nette n'est pas forcément le bon produit et peut ne pas être licenciée.
- Le choix automatique des inserts n'interprète pas la sémantique des phrases.
- La correspondance précise des phonèmes et des mouvements de lèvres exige une relecture humaine ou un modèle de synchronisation adapté ; non implémenté en V6.
- Créer de toutes pièces une nouvelle influenceuse photoréaliste n'est pas une fonction offerte par cette version offline.
- Les sources de l'exemple synthétique ne doivent pas être publiées comme publicité réelle.

Aucun dépôt GitHub ni service distant n'a été modifié.
