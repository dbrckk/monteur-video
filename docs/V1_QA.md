# Validation V1 — preuve et limites

## Validations automatisées

Les workflows GitHub Actions du dépôt exécutent :

- **CI unitaire / API / vrais médias** : import HTTP reprenable, identifiants idempotents, restauration SQLite après redémarrage, reprise d'un rendu échoué, nettoyage automatique des fichiers périmés, permissions CORS et liens de téléchargement HMAC limités au filtre.
- **Exports réels FFmpeg** : deux rushs de couleurs différentes (avec/sans audio), montage H.264/AAC en 9:16 et 16:9, six filtres colorimétriques encodés en MP4.
- **Parcours HTTP intégré** : upload de deux vidéos en blocs, création d'un projet, attente du worker FFmpeg, récupération du master, génération d'un filtre, téléchargement de la variante et suppression des sources.
- **Image Docker** : vérification de Compose local + Quick Tunnel, démarrage réel du serveur Python protégé, vérification des routes, image Whisper complète installée et **initialisation effective d'un modèle CPU Tiny**.
- **Navigateur mobile émulé** : Chromium avec écran 393×852 et événements tactiles, sélection/reclassement de deux vidéos, import réel, rendu asynchrone, filtre Impact, téléchargement MP4 et suppression via le bouton de l'interface.

Les validations CI n'envoient pas les rushs de l'utilisateur vers un service tiers ; elles génèrent des vidéos synthétiques sous licence libre, temporaires sur l'agent GitHub Actions.

## Essai matériel à réaliser

Une vraie vérification de compatibilité depuis un **smartphone Android** et un PC personnel, tous deux connectés à Internet, est nécessaire avant d'affirmer que le tunnel public fonctionne pour des vidéos volumineuses en conditions réelles.

Scénarios prioritaires :
1. Démarrer Docker et un tunnel authentifié, vérifier la session depuis Chrome Android en Wi-Fi puis sur réseau mobile.
2. Transférer deux vidéos réelles avec codecs/durations/résolutions différents, interrompre volontairement l'envoi puis reprendre.
3. Verrouiller l'écran **après** le transfert complet ; vérifier que le montage continue côté PC et que le résultat est retrouvable plus tard.
4. Vérifier les sous-titres issus d'une véritable voix enregistrée et la qualité des images recadrées.
5. Exporter le filtre Impact et télécharger Original et Impact distinctement dans les fichiers du téléphone.
6. Redémarrer le serveur pendant un traitement long ; vérifier la remise en file d'attente et la reprise du suivi.
7. Tester l'espace disque insuffisant, une vidéo corrompue, une clé incorrecte et la disparition du tunnel.

## Limites explicites

- La sélection d'extraits est fondée sur des heuristiques (plans, silences, transcription). **Pas encore de cadrage intelligent de la personne, de synchronisation musicale ni de montage cinématographique garanti.**
- Les filtres sont des préréglages FFmpeg. La simulation CSS immédiate est approximative, et le rendu réel demande une nouvelle tâche CPU.
- Une version gratuite et statique du site ne fournit pas de calcul cloud. Le moteur est exécuté sur un PC actif ; l'URL Cloudflare Quick Tunnel est temporaire, Tailscale Funnel donne une adresse plus stable mais nécessite l'installation et la configuration d'un compte gratuit.
- Le navigateur Android peut suspendre les envois lors du verrouillage ou de la fermeture de l'onglet. La reprise nécessite parfois de sélectionner les fichiers de nouveau.
- Un seul processus de serveur et un seul worker de rendu doivent être utilisés (valeur par défaut du Dockerfile), afin d'éviter des traitements concurrents non coordonnés.

Voir [Démarrer Android + moteur HTTPS](REMOTE_ANDROID.md).
