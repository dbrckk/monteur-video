# Preuves articulaires pour les montages de sport

## But

L'analyse des mouvements repose d'abord sur les signaux FFmpeg (mouvement, netteté, éclairage) et, lorsque le modèle local est disponible, sur les **points de pose réellement visibles** avec Google MediaPipe **Tasks**. Cette seconde voie détecte seulement des transitions de flexion/extension du **coude** ou du **genou**.

Elle ne prétend jamais reconnaître un squat, une traction, une personne précise, le nombre de répétitions ou la bonne technique. Les étiquettes d'exercices diffusées restent exclusivement issues des paroles réellement transcrites, comme auparavant.

## Déroulement

1. Le modèle officiel `pose_landmarker_lite.task` est téléchargé une fois pendant la construction Docker. Aucune image du client n'est envoyée à un service externe.
2. Sur au plus **trois fenêtres d'analyse vidéo**, le moteur décode au maximum huit petites images RGB par fenêtre (192 × 256, 1 image/s). Le détecteur pose est lancé en mode **VIDEO** sur CPU, avec timestamps croissants.
3. Les prises avec plusieurs personnes visibles simultanément, articulations occultées ou déplacements brutaux du buste sont rejetées. Les fenêtres analysées séparément ne sont jamais fusionnées pour produire de faux cycles.
4. Un intervalle est admis si au moins six positions valides et au moins trois transitions flexion/extension sont observées, avec une amplitude minimale de 22° pour le genou ou 28° pour le coude.
5. L'intervalle est comparé aux candidats du montage. S'il couvre au moins 55 % du plan et que la confiance est suffisante, il attribue un **petit bonus de sélection (maximum 0,9)**. Les autres critères de qualité et de chronologie restent prioritaires.

Le moteur publie `action_story.pose_evidence`, `action_story.selected_joint_motion_windows` et garde le champ `actual_pose_or_repetition_recognition=false`.

## Déploiement et arrêt

L'image Docker complète active l'analyse locale avec `MONTEUR_ENABLE_POSE=1`; elle inclut MediaPipe Tasks et le modèle requis. Une installation légère sans modèle fonctionne toujours avec FFmpeg.

Définir `MONTEUR_ENABLE_POSE=0` désactive cette analyse, notamment si le processeur est insuffisant ou en cas de restrictions opérationnelles. Les limites temporelles d'extraction sont appliquées par FFmpeg ; aucune pose n'est nécessaire pour produire l'export. Une erreur MediaPipe retourne un statut `unavailable` et le montage continue sans bonus.

## Contrôles

- Tests unitaires : visibilité et présence des coudes ; cycles articulaires ou données discontinues ; absence de fausse répétition ; sélection pondérée ; repli sans modèle.
- Export réel FFmpeg : vérification d'un MP4 vertical final et de métadonnées correspondant aux plans sélectionnés.
- Smoke test Docker : chargement du vrai modèle via l'API Tasks et analyse effective d'un MP4 généré par FFmpeg.

**Limites :** à une image/seconde, les gestes rapides et exercices complexes ne peuvent pas être reconstruits précisément. Les autres personnes, occlusions ou mouvements du cadre diminuent la fiabilité. Les temps non analysés demeurent inconnus. Une appréciation humaine sur des rushs sportifs autorisés est nécessaire pour valider la valeur artistique des choix.
