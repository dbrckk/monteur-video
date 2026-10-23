# Continuité réelle entre rushs — vérification V1

## Ce qui est mesuré

Après les rendus FFmpeg de chaque rush, le montage analyse uniquement **une petite image au début et à la fin de chaque fichier MP4 réellement exporté** (32 × 18 pixels, RGB). Il compare la luminance et la dominante colorée via la différence moyenne des canaux RGB d'une fin de rush au début du suivant.

Ce contrôle corrige une limite de l'analyse des rushs d'origine : les moyennes des vidéos complètes ne décrivent pas nécessairement les images qui seront voisines dans le montage final.

Pour 5 à 10 rushs et **uniquement en absence de chronologie fiable**, un algorithme de programmation dynamique minimise le coût de jonction, avec une pénalité de déplacement par rapport au récit original. **Le premier et le dernier rush ne bougent jamais.** Le changement est accepté uniquement s'il améliore suffisamment le résultat. Les horodatages caméra, dates ancrées et noms horodatés conservés par le moteur chronologique ne sont jamais supplantés.

Les rushs ne sont pas réencodés : seuls l'ordre du manifeste de concaténation et les métadonnées de sortie changent. Le rendu garde la validation MP4 existante, les caractéristiques H.264/AAC et la publication atomique. Une extraction FFmpeg défectueuse ou un jeu de rushs trop court conserve immédiatement l'ordre initial.

## Métadonnées

Pour les montages multirush, `cut_continuity` indique `evaluated`, `reordered`, la méthode et, si toutes les mesures sont disponibles, `boundary_color_jump_before` / `boundary_color_jump_after`. Ces scores sont un **indicateur de cohérence colorée**, pas un indice d'amélioration narrative ou un score perceptuel absolu.

`sequence_order`, `sources[*].sequence_position`, `clips[*].sequence_position` et les textes de transcription restent synchronisés avec l'ordre réellement concaténé.

## Limitations importantes

- Une moyenne RGB n'identifie pas la personne, l'action, le sens d'un mouvement ou le cadrage optimal. Deux plans de couleur similaire peuvent représenter des événements incompatibles.
- La comparaison se fait sur les bords des rushs déjà montés, pas nécessairement sur chaque raccord interne à un rush.
- Aucun fondu ajouté artificiellement ; un raccord franc peut être préférable pour un montage sportif.
- Les tests incluent de vrais MP4 générés localement, les séquences fixes et les reprises en cas d'échec. Une validation qualitative avec des vidéos sportives autorisées reste nécessaire avant d'affirmer une qualité cinématographique.

La fonctionnalité ne nécessite aucun modèle d'IA supplémentaire, service payant ou nouvelle dépendance.
