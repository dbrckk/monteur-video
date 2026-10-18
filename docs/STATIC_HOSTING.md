# Site statique gratuit

Interface : https://dbrckk.github.io/monteur-video/

La publication est automatisée par GitHub Actions via le dossier web/. Dans Settings > Pages, choisir **GitHub Actions** comme source de publication si GitHub ne l'a pas déjà activé.

**Limite fondamentale :** GitHub Pages héberge uniquement le frontend. L'analyse vidéo, FFmpeg et Whisper nécessitent un moteur Python sur une machine distincte. Un site statique ne peut pas rendre des heures de vidéo sur un serveur gratuitement par lui-même.

Pour une utilisation privée sur PC, lancer le moteur avec Docker Compose puis ouvrir http://localhost:8000 (la même interface est servie par FastAPI). Pour relier le site GitHub Pages à un moteur distant, exposer le moteur sur une URL HTTPS et saisir cette origine dans le champ « Adresse HTTPS du moteur ».

**Sécurité :** la version actuelle de l'API utilise des cookies SameSite=strict, qui ne fonctionnent pas entre github.io et un domaine API distinct. Il faut un proxy d'authentification et une politique CORS contrôlée, ou servir le frontend depuis le même domaine que l'API, avant d'utiliser le site public avec un moteur distant. Ne jamais publier le moteur sans authentification. Le site statique seul reste utilisable pour afficher l'interface mais ne peut pas produire de montage.

L'hébergement permanent gratuit d'un serveur capable de traiter plusieurs heures de vidéo n'est pas garanti. Une machine personnelle avec FFmpeg peut fournir le calcul sans coût d'abonnement, sous réserve de sa disponibilité et de ses ressources.
