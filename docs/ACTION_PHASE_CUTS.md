# Protection des phases d'action dans les raccords sportifs

## Contrat du moteur

L'amélioration des couleurs des raccords ne doit jamais créer un faux récit sportif. Depuis ce changement, chaque rush **déjà sélectionné** reçoit un profil de mouvement mesuré :

- `observed_effort` : la majeure partie du rush exporté est couverte par des intervalles de mouvement soutenu effectivement analysés.
- `measured_low_motion` : des images valides et contiguës attestent un mouvement faible ; cela ne veut **pas** dire repos, récupération ou préparation biologique.
- `mixed` : les images échantillonnées sont suffisantes, mais le rush combine des phases ou n'entre dans aucune catégorie fiable.
- `unknown` : les images valides couvrent moins de 55 % de la durée sélectionnée, ou moins de quatre images sont disponibles. L'inconnu n'est pas interpolé à travers les intervalles non analysés.

Les profils s'appuient exclusivement sur les **clips conservés dans la vidéo finale**, non les pics d'activité des rushs éliminés. Les zones de mesure ont une portée de seulement 0,25 s autour de chaque image analysée. Les épisodes d'action reconnus sont des **intervalles de mouvement visuel**, pas des répétitions d'exercice ou une reconnaissance biomécanique.

## Ordre des vidéos et sécurité

Lorsqu'au moins deux types de phases observées fiables apparaissent, l'optimiseur des couleurs peut seulement déplacer des rushs à l'intérieur de groupes **contigus de même phase**. Il ne franchit jamais une transition vers un autre groupe, un rush inconnu ou mixte. Les rushs inconnus sont des ancres indépendantes, non des groupes librement échangeables.

Les protections précédentes sont inchangées : le premier et le dernier rush demeurent fixes, les horodatages caméra fiables priment sur toutes les heuristiques, et les cas sans signal de phase suffisant utilisent l'optimiseur RGB déjà validé.

Aucune image supplémentaire n'est enregistrée sur disque pour cette protection. Les calculs utilisent les mesures FFmpeg existantes, sans modèle supplémentaire, sans service externe et sans frais. Les MP4 ne sont pas réencodés pour réordonner les plans.

## Observabilité et limites

Chaque source fournit `sources[*].selected_motion_profile` avec sa phase et la fraction de la durée analysée. La liste `selected_motion_phase_order` reflète l'ordre **effectivement concaténé**. `cut_continuity.phase_guard_enabled` confirme l'application du verrou de phases, et `phase_protected_transitions` renseigne le nombre de frontières de groupes protégées.

Cette protection évite certaines inversions manifestes mais ne reconstruit **pas** la véritable chronologie des exercices lorsque les métadonnées sont absentes. Le mouvement de caméra, les variations de lumière, les machines et autres sportifs peuvent fausser l'estimation. Un test qualitatif sur des vidéos sportives autorisées reste nécessaire pour juger l'effet narratif.

## Validation

Le module `tests/test_phase_guard.py` couvre : classification de clips conservés, lacunes de mesure, vidéos figées, fiabilité insuffisante, détections d'action dupliquées, résistance à l'optimisation purement colorimétrique, repli en données inconnues et vraie concaténation FFmpeg de cinq rushs avec métadonnées concordantes.
