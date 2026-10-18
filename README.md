# Monteur Studio — montage automatique fitness / motivation

Application web **mobile-first** avec moteur local ou distant sécurisé, construite pour produire de vrais montages à partir de longues vidéos, et non de démonstrations synthétiques. Importation de **1 à 10 vidéos pour un seul montage**, reprenable par blocs de 8 Mio, analyse FFmpeg des scènes et silences, transcription facultative via faster-whisper, assemblage des clips issus de chaque rush, incrustation de sous-titres, filtres colorimétriques sélectionnables **après le premier rendu**, export **9:16 (Instagram/Reels/Shorts)** ou **16:9 (YouTube)** en H.264/AAC, description française et hashtags.

**État : V1 fonctionnelle et validée en tests, sous réserve de disposer d'un ordinateur hébergeant le moteur.** Ce moteur n'est pas encore un éditeur haut de gamme entièrement automatique. Le recadrage est centré et non intelligent ; la sélection des moments forts repose sur des heuristiques, et aucune musique ou effet visuel tiers n'est injecté sans droits. Les fonctions sont soumises à une CI qui tente un véritable encodage des deux formats.

## Bêta HTTPS Render (2026-10-18)

Une instance gratuite de démonstration a été créée : **https://monteur-video-beta.onrender.com**. L'interface statique GitHub Pages utilise désormais cette adresse par défaut ; la clé d'accès n'est **pas** intégrée au code et doit être renseignée par l'utilisateur. La clé est configurée uniquement dans les variables d'environnement du service Render.

Configuration gratuite de précaution : `MONTEUR_RENDER_SIZE=360` (360×640 pour Reels), `MAX_UPLOAD_GB=0.35` par fichier, `UPLOAD_TTL_HOURS=6`, `RESULT_TTL_DAYS=1`. Les fonctionnalités d'édition (1–10 sources, filtres et export) sont identiques mais les vidéos longues/volumineuses et les gros projets peuvent dépasser les ressources gratuites.

**Avertissement :** Render Free peut mettre l'instance en veille et effacer les fichiers du disque éphémère lors d'un redémarrage ou déploiement. Aucun stockage persistant n'est configuré. Ne pas utiliser pour des rushs irremplaçables ; conserver les originaux sur le téléphone. La transcription Whisper est désactivée dans cette image allégée, mais les montages FFmpeg et les filtres fonctionnent. Cette bêta n'est pas une garantie de stabilité pour des vidéos de plusieurs heures.

## Site web gratuit — Android / smartphone

**Site officiel gratuit et vérifié : https://dbrckk.github.io/monteur-video/**. La publication GitHub Pages est opérationnelle via GitHub Actions. **Miroir gratuit vérifié : https://snappy-gate-x58qpre.shipstatic.com**.

**Important :** les deux hébergeurs statiques ne traitent pas les vidéos. Le moteur FFmpeg se lance maintenant gratuitement sur votre PC avec un tunnel HTTPS et une clé secrète créée automatiquement. Il faut garder cet ordinateur allumé pendant le traitement.



L'interface statique est **déjà publiée sur https://dbrckk.github.io/monteur-video/** et est compatible Android (installation facultative sur l'écran d'accueil). Elle peut s'ajouter à l'écran d'accueil Android (PWA).

**Parcours smartphone :** sélectionner simultanément jusqu'à 10 vidéos dans la galerie Android, les envoyer une à une par blocs reprenables, puis produire **un seul MP4** incluant des moments de chaque rush. Laisser l'onglet ouvert durant l'envoi ; le traitement continue côté serveur après fermeture. Lorsque le montage est disponible, choisir parmi les filtres recommandés selon le thème (fitness, motivation, sport, lifestyle), appliquer celui souhaité sans perdre le master original, puis télécharger la version choisie sur le téléphone.

L'interface seule ne peut pas produire le montage : il faut connecter par HTTPS un serveur personnel qui exécute FFmpeg et Whisper. Les requêtes depuis GitHub Pages sont autorisées par CORS explicite et nécessitent `APP_API_TOKEN` dans l'en-tête Authorization. Les téléchargements passent par un lien temporaire signé ; la clé API n'apparaît pas dans l'URL.

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
