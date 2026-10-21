# Monteur Studio — montage automatique fitness / motivation

Application web **mobile-first** avec moteur local ou distant sécurisé, construite pour produire de vrais montages à partir de longues vidéos, et non de démonstrations synthétiques. Importation de **1 à 10 vidéos pour un seul montage**, reprenable par blocs de 8 Mio, analyse FFmpeg des scènes et silences, transcription facultative via faster-whisper, assemblage des clips issus de chaque rush, incrustation de sous-titres, filtres colorimétriques sélectionnables **après le premier rendu**, export **9:16 (Instagram/Reels/Shorts)** ou **16:9 (YouTube)** en H.264/AAC, description française et hashtags.

**État : V1 disponible gratuitement sur moteur HD hébergé, mais avec stockage éphémère ; un hébergement personnel offre davantage de contrôle.** Ce moteur n'est pas encore un éditeur haut de gamme entièrement automatique. Le recadrage est centré et non intelligent ; la sélection des moments forts repose sur des heuristiques, et aucune musique ou effet visuel tiers n'est injecté sans droits. Les fonctions sont soumises à une CI qui tente un véritable encodage des deux formats.

## Moteur HD gratuit stable (2026-10-18)

L'interface publique [Monteur Studio](https://dbrckk.github.io/monteur-video/) utilise **https://monteur-video-stable.onrender.com**, sans clé d'accès à saisir. Ce service Render Free est fixé à la branche GitHub `release/hd-stable`, avec **déploiement automatique désactivé** : les changements de `main` ne provoquent plus l'arrêt d'un montage en cours. Les mises à jour du moteur doivent être validées et déployées séparément, de préférence hors traitement actif.

- Export **HD 720p uniquement** : 720×1280 (vertical) ou 1280×720 (horizontal).
- Jusqu'à **10 vidéos par montage**, import séquentiel reprenable ; **350 Mio environ par fichier** sur ce serveur, selon l'espace réellement disponible.
- Durée automatique ou cible de **10 à 180 secondes**, filtres et MP4 H.264/AAC.
- Aucune clé demandée à l'utilisateur sur la démonstration publique ; les moteurs privés conservent l'authentification.
- Le navigateur relance un transfert dont la session a disparu après un redémarrage ; si un montage retourne 404, il tente une nouvelle importation **une seule fois** tant que les fichiers sont encore sélectionnés. Après fermeture/rechargement de la page, il faut parfois sélectionner à nouveau les originaux.
- **Important : le disque Render Free reste éphémère**, même avec ce déploiement stable. La mise en veille, un incident ou un redémarrage peuvent toujours faire disparaître les sources, les projets et les MP4 avant leur durée indicative d'expiration. **Cela ne remplace pas un stockage persistant**. Conserver les vidéos d'origine sur le téléphone et télécharger le résultat dès qu'il est disponible.

Les anciennes instances `monteur-video-beta` et `monteur-video-hd` ne sont plus les points d'accès par défaut. La transcription Whisper est désactivée sur le moteur gratuit allégé ; aucune transcription/sous-titre n'est inventé lorsque ce module est absent.

## Montage automatique cohérent et suivi de progression

Le moteur compose désormais une **progression visuelle indépendante de l'ordre d'importation** : plan d'ouverture relativement calme, effort croissant, moment fort, conclusion plus posée. Le classement repose sur le mouvement et le niveau de détail des images échantillonnées, avec un départage déterministe par contenu. Il ne reconnaît pas encore les exercices, les personnes, les émotions ou la chronologie réelle des événements ; les rushs ambigus peuvent donc nécessiter une sélection manuelle dans une version ultérieure.

Les longs rushs sont analysés sur des fenêtres réparties sur toute leur durée, avec recherche FFmpeg bornée (24 secondes échantillonnées par rush par défaut, `MONTEUR_ANALYSIS_SECONDS` configurable). Cela réduit les décodages exhaustifs sur hébergement gratuit. Les progressions `probe`, `scenes`, `quality`, `story` et `render` correspondent désormais à des étapes réelles. L'analyse des silences audio, inutilisée pour décider quels mouvements sportifs conserver, n'est plus effectuée.

L'encodage est limité en threads et les sous-clips ont de légers fondus audio aux points de coupe, sans musique externe ajoutée. Chaque sous-processus FFmpeg critique dispose d'une limite de temps ; un échec explicite est préférable à un montage bloqué indéfiniment. Comme les images ne sont échantillonnées qu'à intervalles pour économiser le CPU, le meilleur mouvement d'un rush très long peut encore passer entre deux fenêtres.

## Protection du matériel de musculation en vidéo 9:16

Quand MediaPipe observe des **poignets visibles** et qu'une longue ligne horizontale contrastée, située près des deux poignets, persiste sur plusieurs images, Monteur Studio repère un **indice visuel de barre longue**. Si la largeur observée ne rentre pas dans une fenêtre 9:16, le montage préserve automatiquement la totalité de l'image originale au centre d'un fond flouté vertical. Le même plan large de sécurité est proposé aux **prises de bras exceptionnellement écartées**, afin de réduire les coupes sur les mains ou les haltères proches des poignets.

Pour les exercices à **un seul bras**, les élévations latérales asymétriques et les mouvements où les deux mains ne sont pas alignées, une troisième sécurité vérifie indépendamment les poignets fiables et l'espace disponible dans le recadrage proposé. Si une main ou l'espace nécessaire à un objet tenu serait coupé pendant la majorité des échantillons, le plan entier passe en fond flouté plutôt que de sacrifier le geste. Les bras brièvement hors cadre, les points de faible confiance et les mouvements isolés ne suffisent pas à déclencher ce choix. Le champ d'export `grip_edge_safe_clips` compte uniquement ces replis géométriques.

Ce système est une protection de composition, **pas une détection IA complète de barres, d'haltères ou de machines**. Une barre oblique, une prise très asymétrique, un appareil immobile ou un objet occulté peut ne pas être reconnu ; à l'inverse, une rambarde horizontale alignée avec les mains peut être prise pour une barre. L'effet protège la scène entière visible dans la source, mais ne peut reconstituer un matériel déjà absent de la vidéo. Les compteurs d'export distinguent `equipment_safe_clips`, `wide_grip_safe_clips`, le suivi de pose et les autres replis. Aucun service supplémentaire ni téléchargement de modèle n'est nécessaire, et tous les plans horizontaux YouTube sont inchangés.

### Détecteur d'objets spécialisé : sélection encore en cours

Des poids réellement entraînés pour les barres et les haltères sont disponibles sur Hugging Face, par exemple [DFine Dumbbell](https://huggingface.co/aguxez/snap-dumbbell-dfine-small-v87-corrected) et [DFine Barbell](https://huggingface.co/aguxez/snap-barbell-dfine-small-v93-v4) (fiches indiquant Apache-2.0), et des modèles ONNX Objects365 contiennent ces classes. **Aucun de ces poids n'est chargé dans la version publique à ce stade** : les premiers demandent encore une pile Transformers/PyTorch non validée en mémoire sur le service gratuit, et les seconds sont trop volumineux pour être activés sans mesures. Le moteur actuel utilise MediaPipe pour le corps et des indices visuels géométriques pour limiter les coupes. Une activation future d'une vraie reconnaissance d'objet exige un modèle local contrôlé, des tests de performances/mémoire et des clips de validation autorisés.

## Recadrage vertical avec détection corporelle locale (MediaPipe)

Sur le moteur Render, un modèle **Google MediaPipe Pose Landmarker Lite** (Apache-2.0) détecte localement les points du corps sur des images des rushs, y compris lorsqu'un sportif ne bouge pas. Le modèle est téléchargé **une seule fois lors de la construction Docker**, pas pendant les montages, et les images du tournage ne sont jamais envoyées à un service de reconnaissance extérieur. L'analyse utilise un flux RGB 320×180, à 1 image/seconde et **14 secondes maximum par plan**, pour limiter la consommation CPU du moteur gratuit. Le suivi conserve de préférence le même sportif lorsqu'une seconde personne entre dans le cadre et amortit les déplacements de caméra.

La priorité du cadrage est : **corps reconnu → mouvement localisé → centre**. Un corps masqué, une faible confiance, une erreur de modèle ou une silhouette trop éloignée activent le repli ; on n'invente jamais une personne détectée. Les extrémités visibles (poignets, chevilles) sont prises en compte, avec une marge visuelle implicite, mais cette version **ne reconnaît pas les haltères, barres ni machines** : leur visibilité complète n'est pas garantie. Les longs plans continuent à partir de la dernière position connue après la fenêtre d'analyse. Les métadonnées distinguent les plans réellement détectés des plans suivis par le mouvement.

L'intégration est **CPU-only et optionnelle**. Construire Docker avec `--build-arg INSTALL_POSE=0` pour économiser la mémoire (l'ancien suivi du mouvement reste disponible), ou définir `MONTEUR_POSE_REFRAME=0` pour désactiver uniquement la détection des silhouettes. `MONTEUR_SMART_REFRAME=0` désactive les deux suivis et force le cadrage centré. L'image Render par défaut contient MediaPipe et le modèle, et le test Docker vérifie son chargement réel.

### Ancien repli de recadrage par le mouvement



Les plans horizontaux exportés en 9:16 ne sont plus systématiquement recadrés au centre. Le moteur analyse **uniquement les segments réellement sélectionnés** via un aperçu FFmpeg limité à 96×54 pixels, 2 images/seconde et 18 secondes par plan. Quand l'activité est suffisamment **localisée**, il déplace horizontalement le cadrage avec interpolation continue et limitation de vitesse ; le changement reste stable pendant le plan. Les sources déjà verticales, les mouvements peu concluants, les changements globaux de lumière et les échecs d'analyse conservent le **recadrage central**, sans bloquer la production. Le rendu horizontal YouTube est inchangé.

**Le système de secours** est une **détection de mouvement**, pas un suivi garanti de personne ni d'équipement. Une personne immobile ou des objets mobiles peuvent être mal cadrés ; ne pas prétendre à une reconnaissance sémantique. L'export signale le nombre de plans effectivement recadrés et le nombre de replis centraux. Pour couper cette analyse sur un moteur personnel : `MONTEUR_SMART_REFRAME=0` (même encodeur et même cadrage centré que précédemment). Les tests CI construisent de vrais MP4 avec un sujet mobile, une animation globale et des cas de repli.

## Bande-son originale, rythme sportif et audio des rushs

Le serveur génère localement une **musique instrumentale originale** selon le thème et l'ajoute au master MP4 final : **Power Session** (fitness, 144 BPM), **Sprint Mode** (sport, 152 BPM), **Rise Again** (motivation, 128 BPM), **Daylight Motion** (lifestyle, 116 BPM), **Momentum** (auto, 136 BPM). Batterie synthétique, basse, motif mélodique et variations de mesures sont calculés par `soundtrack.py`, sans télécharger ni réutiliser de morceaux commerciaux, d'échantillons tiers ni de musiques issues de TikTok/Instagram.

Sur smartphone, le son du fichier source est réglable :
- **Auto** (par défaut) : son des rushs **coupé**, sauf si une vraie transcription a identifié de la parole dans le montage, auquel cas le son d'origine est à **20 %**.
- **Couper** : son d'origine à **0 %**.
- **20 %** : conserver légèrement la voix et les bruits de la séance en fond de musique.

Lorsque le son capté par le micro est conservé à 20 %, le niveau de la musique originale baisse automatiquement pendant les passages sonores (compression dynamique sidechain FFmpeg), puis remonte progressivement. Ce mécanisme se base sur l'énergie réelle du micro, pas sur une reconnaissance fiable de la parole : une ambiance bruyante peut également provoquer l'atténuation. En absence de piste audio, une musique originale est quand même ajoutée, sans troncature ni piste son fictive attribuée à la source. Le mix final dispose d'un limiteur de crête.

Les clips de sport et musculation sont réduits à des phrases de **8 temps environ**, avec une préférence pour les durées multiples de **4 temps** et des coupes franches calées sur le tempo du morceau généré. La musique reste continue pendant tout le montage, même si les rushs changent d'ordre, et les coupes audio sources bénéficient de fondus très courts.

Ces instrumentaux originaux fournissent une solution utilisable gratuitement et sans clé, mais ne prétendent pas être des musiques populaires sous licence TikTok ni un catalogue professionnel produit par des artistes. Sans Whisper, l'option automatique ne peut pas déterminer si la voix est intéressante : elle privilégie donc la musique seule. Les métadonnées d'export indiquent la musique, le BPM, sa provenance et le niveau de son source réellement utilisé.

### Sélection musicale directement adaptée aux images (V2)

La V2 analyse les signaux vidéo FFmpeg déjà calculés (intensité des mouvements, qualité/luminosité et fréquence de changement des plans), puis choisit une **direction musicale distincte pour chaque montage** : échauffement posé, entraînement régulier ou action intense. Par exemple, le même thème fitness peut aboutir à **120, 136 ou 154 BPM**. La piste originale est ensuite générée à ce tempo, et les séquences sportives utilisent le même tempo pour choisir des durées de coupe sur les mesures. L'analyse agrégée sur plusieurs rushs ne dépend pas de leur ordre d'import.

Cette fonction s'inspire du **principe d'appariement entre musique et vidéo**, mais ne reproduit ni le catalogue TikTok, ni son moteur de recommandation propriétaire, ni des morceaux d'artistes non licenciés. La détection reste fondée sur des heuristiques visuelles, sans classification sémantique des exercices ni analyse des goûts personnels. Si les images sont trop sombres ou les signaux insuffisants, le thème fournit un choix musical de secours.

## Musiques populaires des Reels, sélectionnées selon la vidéo

**Mode Reels Instagram (par défaut dans le studio mobile).** À partir de la sélection des meilleurs plans et des mesures de mouvement, le moteur attribue une énergie visuelle au montage. Il parcourt alors les classements thématiques **SoundMatcha** basés sur les pages audio publiques de Reels Instagram (musculation, sport/énergie, motivation, lifestyle), classe les titres et retient le meilleur candidat avec deux alternatives. Le résultat indique le nom du morceau, l'artiste et un lien direct vers la page audio Instagram lorsqu'elle est identifiable. Si le classement public est indisponible, un jeu de liens déjà vérifiés est utilisé et cette origine de secours est signalée.

**Pour publier avec un morceau commercial :** le moteur produit un MP4 HD où le son des rushs est coupé (ou conservé à 20 % si demandé). Après le rendu, ouvrir la piste recommandée dans Instagram, utiliser le son depuis sa page, choisir le MP4 exporté dans la galerie et publier. **La piste commerciale n'est jamais téléchargée depuis un Reel, réencodée ou incluse dans l'export MP4 par notre serveur.** Instagram applique ses propres accords selon le compte, le pays et l'usage lors de l'ajout dans son application. Une musique existant sur Instagram n'est pas nécessairement autorisée pour une publicité, un compte professionnel ou une redistribution sur YouTube.

Le logiciel ne dispose pas d'une API publique garantie pour indexer toutes les vidéos similaires d'Instagram ou pour ajouter automatiquement une musique populaire à un fichier MP4 tiers. Il s'agit donc d'une correspondance basée sur **un catalogue public de musiques réellement employées dans le même genre de Reels**, et sur l'énergie des images, non d'un clone exact de l'algorithme propriétaire de Meta ni d'une authentification à Instagram. Les titres instrumentaux ne sont certifiés que lorsque leur intitulé l'indique ; sinon la présence de paroles est notée inconnue. Aucun BPM d'un morceau tiers n'est inventé, et la synchronisation stricte sur ses battements reste une étape manuelle dans l'éditeur Instagram.

Le mode **Musique originale intégrée au MP4** demeure disponible et produit une composition instrumentale embarquée directement dans le MP4 pour une publication multi-plateforme sans musique commerciale externe.

Source : https://soundmatcha.com/for/gym/ — classement public à citer par lien. Conditions musicales de Meta : https://www.facebook.com/help/instagram/402084904469945 . Contrat CapCut : https://www.capcut.com/clause/material-license-agreement .

## Analyse des articulations — module expérimental optionnel

Le moteur peut, sur une infrastructure disposant d'une version **MediaPipe Solutions Pose** compatible et de NumPy, examiner au plus 24 images basse résolution réparties sur les rushes et rechercher des changements visibles d'angle aux genoux. Activer explicitement `MONTEUR_ENABLE_POSE=1` **uniquement après installation et validation du runtime ML**. Par défaut, cette fonction est désactivée afin de préserver la compatibilité du serveur gratuit : le montage continue avec ses indicateurs de mouvement classiques.

Lorsque les articulations sont masquées, que le signal est trop faible ou que les échantillons sont espacés, aucune conclusion n'est produite. Les angles peuvent signaler une flexion-extension visible, **pas identifier avec certitude un squat**, évaluer une technique ni compter des répétitions d'exercice. Les métadonnées distinguent explicitement les analyses mesurées, indisponibles ou désactivées.

## Chronologie de tournage et étalonnage automatique

Le moteur utilise les métadonnées de **date/heure de capture** de FFprobe et QuickTime (fuseau horaire compris) pour reconstruire la séquence réelle, **quel que soit l'ordre d'import des fichiers**. Les clips internes à chaque rush restent temporellement ordonnés. Lorsque les informations de capture sont manquantes ou non comparables, le système évite les dates de modification trompeuses : il revient à une progression visuelle déterministe introduction → effort → pic → conclusion. Cette solution ne prétend pas deviner l'ordre réel d'événements impossibles à distinguer visuellement sans dates de capture.

L'**étalonnage automatique** s'appuie sur les mesures de chaque rush, réalisées pendant l'analyse visuelle existante : luminance Y et chrominances U/V. Le moteur construit une référence robuste issue de plusieurs vidéos puis limite les corrections de luminosité, balance colorimétrique et contraste/saturation par thème. Les séquences sous-exposées, complètement noires ou insuffisamment analysées ne reçoivent pas de correction agressive. L'étalonnage est intégré à l'encodage des extraits (sans deuxième encodage complet), et ses coefficients ainsi que la stratégie chronologique sont consultables dans les métadonnées de sortie.

Limites : ce processus n'effectue pas de reconnaissance sémantique des exercices, suivi du visage ou correspondance 3D de la scène ; il ne remplace pas un étalonneur professionnel sur des images très sous-exposées ou des caméras aux espaces colorimétriques incompatibles.

### Reconstruction chronologique et étalonnage plan par plan — amélioration

Quand les métadonnées caméra ont disparu, l'application essaie désormais des **dates intégrées aux noms de fichiers d'origine** (formats de caméra `VID_YYYYMMDD_HHMMSS`, `PXL_...`, `IMG_...`), à condition que **tous les rushes** présentent des noms de capture interprétables et qu'aucun fuseau horaire contradictoire ne soit à comparer. Si plusieurs dates de tournage fiables sont présentes mais qu'il manque celles d'autres clips, elles servent de **points d'ancrage dont l'ordre est préservé** ; les rushes non datés sont intercalés selon la progression visuelle. Les métadonnées distinguent `capture_time`, `camera_filename_time`, `capture_anchors_visual_gaps` et `energy_arc_no_reliable_timestamps`. Sans horodatage sûr, aucune méthode ne peut garantir l'ordre chronologique réel ; on ne le prétend pas.

L'étalonnage est maintenant **adaptatif pour chaque passage retenu**, avec correction locale de luminosité et de composantes U/V, en utilisant la référence de couleur commune à tout le montage. Les corrections restent bornées (y compris dans les hautes lumières et les ombres extrêmes) et reviennent à la correction par rush lorsque les échantillons locaux sont insuffisants. Cela réduit les ruptures d'exposition **à l'intérieur même d'une longue prise**, et pas seulement entre vidéos distinctes.

## Site web gratuit — Android / smartphone

**Site officiel gratuit et vérifié : https://dbrckk.github.io/monteur-video/**. La publication GitHub Pages est opérationnelle via GitHub Actions. **Miroir gratuit vérifié : https://snappy-gate-x58qpre.shipstatic.com**.

**Important :** les deux hébergeurs statiques ne traitent pas les vidéos. Le moteur FFmpeg est disponible sur Render Free sans clé pour un usage d'essai. Un PC personnel avec tunnel HTTPS reste une alternative pour des fichiers plus volumineux ou un traitement privé.



L'interface statique est **déjà publiée sur https://dbrckk.github.io/monteur-video/** et est compatible Android (installation facultative sur l'écran d'accueil). Elle peut s'ajouter à l'écran d'accueil Android (PWA).

**Parcours smartphone :** sélectionner simultanément jusqu'à 10 vidéos dans la galerie Android, les envoyer une à une par blocs reprenables, puis produire **un seul MP4** incluant des moments de chaque rush. Laisser l'onglet ouvert durant l'envoi ; le traitement continue côté serveur après fermeture. Lorsque le montage est disponible, choisir parmi les filtres recommandés selon le thème (fitness, motivation, sport, lifestyle), appliquer celui souhaité sans perdre le master original, puis télécharger la version choisie sur le téléphone.

L'interface seule ne peut pas encoder : elle utilise le serveur FFmpeg HD préconfiguré, ou un moteur personnel. Le moteur public fonctionne sans clé ; le mode privé exige `APP_API_TOKEN` dans l'en-tête Authorization. Les téléchargements passent par un lien temporaire signé ; la clé API n'apparaît pas dans l'URL.

**[Guide de démarrage V1 Android + moteur gratuit en HTTPS](docs/REMOTE_ANDROID.md)** : une commande Linux/macOS ou Windows, clé API générée, Cloudflare Quick Tunnel temporaire. En option, Tailscale Funnel permet de conserver une adresse HTTPS stable avec un compte Personal gratuit. **[Documentation technique de l'hébergement statique](docs/STATIC_HOSTING.md)**.



## Démarrer le moteur Docker sur PC

Docker et Docker Compose v2 s'installent sur l'ordinateur qui héberge l'application, pas sur le téléphone Android.

~~~bash
git clone https://github.com/dbrckk/monteur-video.git
cd monteur-video
docker compose up --build -d
~~~

Ouvrir http://localhost:8000 sur la machine hôte. Pour utiliser **le site public Android** avec ce moteur sans configurer de routeur, utiliser le script de démarrage gratuit :

~~~bash
bash scripts/start-free.sh
~~~

Sur Windows : `powershell -ExecutionPolicy Bypass -File .\\scripts\\start-free.ps1`. Pour une adresse HTTPS Tailscale plus stable : `bash scripts/start-stable.sh` (nécessite l'installation et l'authentification à Tailscale). Les scripts générent `APP_API_TOKEN` et affichent l'adresse HTTPS à renseigner dans le site Android. Les URL Quick Tunnel peuvent changer et n'ont pas de garantie de disponibilité. Compose seul continue de publier uniquement sur localhost par sécurité.

Pour protéger l'API par session, créer un fichier local nommé .env :

~~~dotenv
APP_API_TOKEN=replace-with-a-strong-random-secret
MAX_UPLOAD_GB=20
WHISPER_MODEL=base
~~~

La page web accepte cette clé et ouvre une session HttpOnly en local ; depuis GitHub Pages, elle utilise un jeton Bearer non sauvegardé sur le téléphone. Le moteur Whisper télécharge son modèle au premier usage si le cache est vide ; la rapidité dépend du CPU ou GPU, de la durée source et des capacités de téléchargement. L'image Docker utilise l'inférence CPU en int8 par défaut.

## Lancer sans Docker

Installer Python 3.12 ou ultérieur, FFmpeg et ffprobe. Linux/macOS :

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-ai.txt
uvicorn server:app --host 127.0.0.1 --port 8000
~~~

Sous Windows activer l'environnement virtuel dans le dossier Scripts. Une installation plus légère sans transcription automatique peut utiliser requirements.txt à la place de requirements-ai.txt. Si Whisper est absent ou indisponible, le moteur continue sans inventer de sous-titres ni de tags issus de la voix.

## API et importation de longues vidéos

### Un montage à partir de plusieurs vidéos

1. Sélectionner 1 à 10 fichiers (MP4, MOV, MKV, WebM, AVI), en gardant l'ordre de sélection voulu.
2. Pour chaque fichier, créer une session `POST /api/uploads`, transférer par `PATCH /api/uploads/{id}` en blocs d'au plus 16 Mio et contrôler l'offset par `GET /api/uploads/{id}`. Les sources peuvent être longues ; elles restent conservées sur le serveur durant le traitement.
3. Créer un **unique montage** par `POST /api/montages` :
   ```json
   {"project_id":"00000000-0000-4000-8000-000000000001","upload_ids":["uuid-video-1","uuid-video-2"],"theme":"fitness","aspect":"vertical","seconds":45}
   ```
   `project_id` est facultatif mais recommandé : un UUID stable rend l'appel rejouable sans produire de doublon en cas de coupure réseau mobile. Les uploads doivent être terminés et chaque source ne peut être consommée que par un montage. Le moteur répartit les secondes entre les rushs, et sélectionne des séquences dans chacun avant concaténation.
4. Interroger `GET /api/jobs/{id}` jusqu'à `done`. Le résultat comprend le nombre de sources, les extraits sélectionnés et la description.

### Filtres recommandés après montage

`GET /api/jobs/{id}/filters` retourne les looks disponibles, présentés en priorité selon le thème : Original, Impact, Acier, Énergie, Cinéma, Soleil, Noir & blanc. Le navigateur affiche un **aperçu CSS approximatif**, pas encore le fichier exporté. `POST /api/jobs/{id}/filters` avec `{"preset":"impact"}` lance un export FFmpeg non destructif dans la file d'attente. Interroger le même endpoint GET jusqu'au statut `done`, puis `GET /api/jobs/{id}/download-link?preset=impact` retourne un lien de téléchargement temporaire lié au filtre. Le master original reste intact et reste téléchargeable avec `preset=original`.


1. POST /api/uploads avec un JSON de la forme {"filename":"session.mp4","size":12345678} renvoie un identifiant UUID.
2. PATCH /api/uploads/{id} reçoit des blocs de données brutes de 16 Mio maximum ; fournir l'en-tête Upload-Offset. En cas d'échec, GET /api/uploads/{id} permet de retrouver l'offset exact et de reprendre.
3. POST /api/uploads/{id}/complete avec {"theme":"fitness","aspect":"vertical","seconds":45} lance la production. Thèmes : fitness, motivation, sport, lifestyle, auto. Formats : vertical ou youtube. Durée : 10 à 180 secondes.
4. GET /api/jobs/{id} expose la progression, le moteur de transcription réellement utilisé, les clips sélectionnés, la description et les hashtags.
5. GET /api/jobs/{id}/download-link renvoie une URL MP4 signée valide pendant 15 minutes ; ajouter `?preset=<id>` pour choisir une version filtrée terminée. Le ticket est lié à l'identifiant du preset : il ne permet pas d'obtenir d'autres versions. DELETE /api/jobs/{id} supprime montage, originaux consommés et variantes terminées.

La durée d'entrée n'a pas de plafond artificiel. La taille maximale par fichier (20 Gio par défaut) dépend aussi de l'espace disque disponible ; 10 fichiers de grande taille peuvent réclamer beaucoup d'espace. Le client envoie plusieurs vidéos dans le même projet, **séquentiellement** pour limiter la mémoire et les interruptions sur Android, pas simultanément sur le réseau. Les longues sources restent coûteuses à décoder et à transcrire. SQLite persiste les états ; **les tâches en file d'attente et les montages/filtres interrompus sont remis en file après un redémarrage** du moteur. En cas d'échec de traitement, `POST /api/jobs/{id}/retry` permet de relancer le montage sans recharger les rushs, si les sources sont encore présentes. Un seul rendu s'exécute simultanément pour protéger la mémoire. Les sources et exports sont conservés **14 jours par défaut** après la fin du traitement (et 72 heures pour les envois abandonnés), ou jusqu'à leur suppression manuelle. Les durées sont configurables via `RESULT_TTL_DAYS` et `UPLOAD_TTL_HOURS`.

## API supplémentaire (V1)

- `GET /api/session` (authentifié) : test du moteur, version, limites d'import et espace disque.
- `POST /api/jobs/{id}/retry` (authentifié) : relance idempotente d'un job en échec, sans nouvel envoi depuis Android.
- `GET /api/jobs/{id}` inclut `expires_at` pour la date limite de récupération des fichiers.
- `GET /api/health` : vérification technique locale et Docker Healthcheck.

## Limites connues et prochaines phases

- Pas encore de suivi automatique du sujet et de recadrage du visage / corps.
- Pas encore de reconnaissance visuelle des exercices : les hashtags spécifiques reposent actuellement sur le contenu réellement prononcé et transcrit.
- Pas encore d'étalonnage cinématographique, transitions avancées, synchronisation avec des battements, ducking musical ou habillage dynamique premium.
- Pas de publication automatique sur Instagram/YouTube. Une vérification humaine du montage et de la description est recommandée.
- La source sonore est conservée ; aucune musique non licenciée n'est ajoutée.

## Vérifier le fonctionnement

~~~bash
pip install -r requirements-dev.txt
python -m compileall -q editor.py montage.py server.py tests
python -m unittest discover -s tests -v
~~~

La suite de validation fabrique des vidéos sources réelles avec FFmpeg, produit les formats verticaux/horizontaux, assemble deux rushs avec et sans son puis teste les six filtres. Un test de bout en bout simule le smartphone avec l'API HTTP (création et reprise des imports, projet, rendu FFmpeg, filtre, lien signé, suppression). Le workflow Docker construit une image légère et **démarre vraiment l'API protégée** ; le workflow de production installe Whisper dans l'image complète. Les tests de reprise et de purge vérifient le comportement après redémarrage. Un autre test examine l'importation reprenable, les offsets, la validation et la mise en file. GitHub Actions exécute ces contrôles à chaque push.

## Composants et recherche

- [FFmpeg](https://ffmpeg.org/) : analyse, transcodage et composition.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) : transcription optionnelle (licence MIT).
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect), [OpenCut](https://github.com/OpenCut-app/OpenCut) et [auto-editor](https://github.com/WyattBlue/auto-editor) : références étudiées pour le développement ultérieur.
- [star-list](https://github.com/dbrckk/star-list) : catalogue open source du projet.

Aucun code externe d'éditeur vidéo n'est recopié ni intégré sans étude de sa licence.

**Sécurité :** exécuter en local par défaut ; utiliser HTTPS et des contrôles d'accès en cas d'hébergement distant. FFmpeg et les bibliothèques vidéo décodent des fichiers non fiables : maintenir les dépendances à jour et limiter les ressources système.

### Limites spécifiques aux rushs multiples et aux filtres

- Pour limiter charge et espace disque, un montage accepte 10 fichiers au maximum ; l'ordre de sélection détermine l'ordre narratif des rushs. Le choix des extraits reste heuristique, avec au moins une seconde visée par source, si chaque entrée est valide et suffisamment longue.
- Les filtres sont des profils FFmpeg prédéfinis et contrôlés, non une génération IA de style ; l'aperçu CSS est indicatif. Le fichier filtré est réencodé avant téléchargement et peut demander du temps supplémentaire sur les vidéos longues.
- Plusieurs exports filtrés peuvent être mis en file d'attente et partagent le worker FFmpeg ; le master n'est pas remplacé. La version originale est conservée.
- Même sur un site statique gratuit, il faut un moteur FFmpeg/Whisper HTTPS accessible en permanence depuis le téléphone. Pas de transfert garanti en arrière-plan après la fermeture de Chrome Android.

### Sélection visuelle intelligente (bêta)

Le mode **Auto** peut proposer un montage de 10 ou 15 secondes, même à partir d'un long rush, lorsque l'activité visuelle est concentrée sur quelques instants. Chaque rush est analysé avec FFmpeg à **2 images/seconde, en 192 px**, sans modèle lourd : variation entre images (mouvement), luminance, détails visuels (proxy de netteté), fonds noirs et images figées. Les passages silencieux sont préservés si l'image montre une activité utile. Les analyses sont réutilisées lors de la sélection pour éviter un second calcul. Si l'analyse visuelle échoue, le montage reste possible avec la sélection classique.

Ces heuristiques **ne reconnaissent pas réellement** les exercices, les personnes ou les mouvements sportifs, et un mouvement de caméra peut être confondu avec l'action. Elles aident à choisir les plans, mais ne garantissent pas la détection du meilleur instant. La résolution publique reste **720p HD**, en portrait ou paysage.

<!-- Stabilisation : validation CI du classement musical par tempo vérifié. -->

## Détection des phases d'action sportive

Le moteur regroupe les échantillons de mouvement adjacents pour distinguer des **séquences d'activité soutenue** des temps plus calmes. Les extraits qui recouvrent effectivement une phase d'action mesurée reçoivent une priorité accrue, sans réordonner les instants à l'intérieur d'un rush. Les intervalles non échantillonnés ne sont jamais fusionnés comme s'ils avaient été observés. La sortie contient les bornes et scores de confiance des phases détectées.

Pour les exercices, un nom comme « squat » ou « développé couché » n'est renseigné que s'il est mentionné explicitement dans une transcription disponible. **Le mouvement de caméra seul n'identifie ni le type d'exercice, ni le nombre de répétitions, ni la pose d'une personne.** Ces fonctions demanderaient un détecteur de pose validé, une localisation corporelle et des tests sur de véritables vidéos d'entraînement ; aucun résultat n'est inventé en leur absence. L'analyse actuelle réutilise les mesures FFmpeg existantes et fonctionne sur l'hébergement gratuit.
