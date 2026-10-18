# Monteur Studio — montage automatique fitness / motivation

Application web **locale** construite pour produire de vrais montages à partir de longues vidéos, et non de démonstrations synthétiques. Importation reprenable par blocs de 8 Mio, analyse FFmpeg des scènes et silences, transcription facultative via faster-whisper, assemblage des clips, incrustation de sous-titres, export **9:16 (Instagram/Reels/Shorts)** ou **16:9 (YouTube)** en H.264/AAC, description française et hashtags.

**État : première version bêta.** Ce moteur n'est pas encore un éditeur haut de gamme entièrement automatique. Le recadrage est centré et non intelligent ; la sélection des moments forts repose sur des heuristiques, et aucune musique ou effet visuel tiers n'est injecté sans droits. Les fonctions sont soumises à une CI qui tente un véritable encodage des deux formats.

## Site web gratuit — Android / smartphone

**Interface actuellement publiée : https://angled-gate-srzt937.shipstatic.com** (hébergement statique gratuit avec déploiement connecté sans date d'expiration indiquée). GitHub Pages reste une seconde adresse possible après activation des Pages dans les paramètres du dépôt.

**Important :** les deux hébergeurs statiques ne peuvent pas traiter des vidéos. Il reste à connecter un moteur de montage HTTPS.



L'interface statique est prévue sur **https://dbrckk.github.io/monteur-video/** avec publication automatique par GitHub Pages, après activation de Pages dans les réglages du dépôt. Elle peut s'ajouter à l'écran d'accueil Android (PWA).

**Parcours smartphone :** choisir la vidéo dans la galerie Android, envoyer le fichier par blocs reprenables, garder l'onglet ouvert durant l'envoi, puis le traitement continue côté serveur même après fermeture. L'application conserve le dernier montage pour retrouver le MP4 et le télécharger depuis le téléphone.

L'interface seule ne peut pas produire le montage : il faut connecter par HTTPS un serveur personnel qui exécute FFmpeg et Whisper. Les requêtes depuis GitHub Pages sont autorisées par CORS explicite et nécessitent `APP_API_TOKEN` dans l'en-tête Authorization. Les téléchargements passent par un lien temporaire signé ; la clé API n'apparaît pas dans l'URL.

Lire **[le guide d'hébergement statique et d'utilisation Android](docs/STATIC_HOSTING.md)** pour le fonctionnement, la sécurité et les limites (notamment : envoi non garanti lorsque l'onglet est fermé).



Docker et Docker Compose sont installés sur l'ordinateur qui héberge l'application, pas sur le téléphone Android.

~~~bash
git clone https://github.com/dbrckk/monteur-video.git
cd monteur-video
docker compose up --build -d
~~~

Ouvrir http://localhost:8000 sur la machine hôte. Pour Android, utiliser un reverse proxy HTTPS avec contrôle d'accès devant le serveur. Ne pas exposer une instance non protégée à Internet. Compose publie uniquement sur l'interface localhost.

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

1. POST /api/uploads avec un JSON de la forme {"filename":"session.mp4","size":12345678} renvoie un identifiant UUID.
2. PATCH /api/uploads/{id} reçoit des blocs de données brutes de 16 Mio maximum ; fournir l'en-tête Upload-Offset. En cas d'échec, GET /api/uploads/{id} permet de retrouver l'offset exact et de reprendre.
3. POST /api/uploads/{id}/complete avec {"theme":"fitness","aspect":"vertical","seconds":45} lance la production. Thèmes : fitness, motivation, sport, lifestyle, auto. Formats : vertical ou youtube. Durée : 10 à 180 secondes.
4. GET /api/jobs/{id} expose la progression, le moteur de transcription réellement utilisé, les clips sélectionnés, la description et les hashtags.
5. GET /api/jobs/{id}/download-link renvoie une URL MP4 signée valide pendant 15 minutes ; GET /api/jobs/{id}/download avec ce ticket télécharge le MP4 sans cookies tiers. DELETE /api/jobs/{id} supprime source et export une fois terminé.

La durée d'entrée n'a pas de plafond artificiel. La taille maximale (20 Gio par défaut) dépend aussi de l'espace disque disponible. Les longues sources restent coûteuses à décoder et à transcrire. SQLite persiste les états ; les tâches mises en file reprennent après un redémarrage, tandis qu'une tâche interrompue en plein rendu passe en état échec. Un seul rendu s'exécute simultanément pour protéger la mémoire. Les fichiers source sont conservés tant que l'utilisateur ne les supprime pas.

## Limites connues et prochaines phases

- Pas encore de suivi automatique du sujet et de recadrage du visage / corps.
- Pas encore de reconnaissance visuelle des exercices : les hashtags spécifiques reposent actuellement sur le contenu réellement prononcé et transcrit.
- Pas encore d'étalonnage cinématographique, transitions avancées, synchronisation avec des battements, ducking musical ou habillage dynamique premium.
- Pas de publication automatique sur Instagram/YouTube. Une vérification humaine du montage et de la description est recommandée.
- La source sonore est conservée ; aucune musique non licenciée n'est ajoutée.

## Vérifier le fonctionnement

~~~bash
pip install -r requirements-dev.txt
python -m compileall -q editor.py server.py tests
python -m unittest discover -s tests -v
~~~

Le test d'intégration fabrique une courte vidéo source avec FFmpeg, produit réellement un MP4 vertical et un MP4 horizontal puis vérifie les dimensions par ffprobe. Un autre test examine l'importation reprenable, les offsets, la validation et la mise en file. GitHub Actions exécute ces contrôles à chaque push.

## Composants et recherche

- [FFmpeg](https://ffmpeg.org/) : analyse, transcodage et composition.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) : transcription optionnelle (licence MIT).
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect), [OpenCut](https://github.com/OpenCut-app/OpenCut) et [auto-editor](https://github.com/WyattBlue/auto-editor) : références étudiées pour le développement ultérieur.
- [star-list](https://github.com/dbrckk/star-list) : catalogue open source du projet.

Aucun code externe d'éditeur vidéo n'est recopié ni intégré sans étude de sa licence.

**Sécurité :** exécuter en local par défaut ; utiliser HTTPS et des contrôles d'accès en cas d'hébergement distant. FFmpeg et les bibliothèques vidéo décodent des fichiers non fiables : maintenir les dépendances à jour et limiter les ressources système.
