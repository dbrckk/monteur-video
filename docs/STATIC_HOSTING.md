# Site statique gratuit : Android en priorité

**Site en ligne vérifié :** https://angled-gate-srzt937.shipstatic.com

**GitHub Pages (en attente d'activation) :** https://dbrckk.github.io/monteur-video/

Le premier workflow GitHub Pages a échoué lors de `actions/configure-pages`, car Pages n'est pas activé dans les réglages du dépôt. L'hébergement statique ShipStatic connecté rend dès maintenant l'interface accessible, gratuitement. Le moteur distant HTTPS reste indispensable pour réellement traiter les vidéos.

GitHub Actions publie le dossier `web/` sur GitHub Pages à chaque changement de `main`. Dans **Settings > Pages > Build and deployment**, sélectionner **GitHub Actions** comme source, si nécessaire. La mise en ligne effective dépend de l'activation Pages et de la réussite du workflow « Publish static studio » : ne pas confondre URL prévue et site déjà publié.

## Utilisation sur smartphone

1. Ouvrir le site depuis Chrome Android, puis éventuellement **Ajouter à l'écran d'accueil** (PWA).
2. Renseigner l'URL HTTPS de son propre moteur de montage (une seule fois ; elle est mémorisée localement).
3. Saisir la clé du moteur, dans l'onglet actif uniquement. Elle n'est pas sauvegardée dans le stockage du navigateur.
4. Sélectionner la vidéo depuis la galerie Android / le sélecteur de fichiers. Choisir 9:16 / 16:9, thème et durée.
5. Garder **l'onglet ouvert pendant le transfert** : Android peut interrompre JavaScript lorsque l'écran est éteint ou le navigateur fermé.
6. En cas de rupture réseau, revenir sur le site, sélectionner **le même fichier** (même nom, taille et date de modification) puis relancer : l'envoi reprend depuis l'octet confirmé par le serveur, sans repartir systématiquement à zéro.
7. Une fois le transfert intégralement terminé, **le traitement continue côté serveur**, indépendamment de l'onglet. Le dernier identifiant de montage est conservé sur le téléphone ; **Retrouver mon dernier montage** et ressaisir la clé au besoin.
8. Après rendu, utiliser **Télécharger le MP4 sur mon téléphone** ; le navigateur Android gère son téléchargement habituel (dossier Téléchargements, selon le navigateur). Le lien de téléchargement temporaire reste valide pendant 15 minutes ; l'application en demande un nouveau en consultant à nouveau le montage.

**La reprise automatique n'est pas un upload en arrière-plan Android garanti.** Les navigateurs mobiles peuvent aussi libérer le fichier sélectionné lorsque la page est rechargée : il faut le sélectionner de nouveau.

## Architecture et sécurité

```text
Chrome Android -> GitHub Pages (interface statique gratuite)
       |
       +--- HTTPS / Authorization: Bearer ... ---> API FastAPI + FFmpeg + Whisper
                                                   sur PC ou machine avec stockage
       <--- lien MP4 signé temporaire --------------+
       |
       +--- téléchargement MP4 depuis l'API HTTPS
```

Le site statique n'héberge **ni fichiers sources, ni vidéos finales, ni moteur IA**. GitHub Pages n'exécute ni Python ni FFmpeg. Le traitement de vidéos de plusieurs Go nécessite CPU/RAM/disque et une machine accessible à distance. La disponibilité permanente d'un hébergement de calcul gratuit n'est pas garantie.

L'API accepte les requêtes depuis les origines explicites `https://dbrckk.github.io` et `https://angled-gate-srzt937.shipstatic.com` (par défaut), plus les origines HTTPS déclarées avec `MONTEUR_CORS_ORIGINS`. Les requêtes sensibles exigent `APP_API_TOKEN`. En mode site statique, l'interface envoie le jeton dans l'en-tête Authorization pour chaque appel API, sans cookies tiers. Le téléchargement est autorisé par un **ticket HMAC signé à validité courte**, évitant de placer la clé API longue durée dans l'URL du MP4.

Exemple de configuration serveur, sur une machine contrôlée :

```dotenv
APP_API_TOKEN=une-cle-longue-unique-et-aleatoire
MAX_UPLOAD_GB=20
# uniquement pour un domaine personnalisé supplémentaire :
MONTEUR_CORS_ORIGINS=https://studio.exemple.fr
```

**Ne jamais publier directement le port 8000 sur Internet sans HTTPS, authentification et protections réseau.** Compose lie par défaut le serveur à `127.0.0.1:8000`. Un proxy ou tunnel HTTPS vérifié doit fournir l'URL du moteur. L'URL publique de l'API ne doit pas contenir la clé. Le moteur doit rester allumé durant le transfert et le rendu ; prévoir assez de disque pour la source et les exports. L'utilisateur doit avoir les droits d'utilisation des vidéos et musiques.

## Limites à résoudre pour la production

- Gestion multi-utilisateurs, quotas, durée de conservation et nettoyage des médias.
- Reprise de rendu interrompu et traitement distribué des tâches longues.
- Test bout-en-bout depuis Chrome Android réel en Wi-Fi et 4G/5G.
- Optimisation des uploads sur réseau mobile variable et sécurisation de l'hébergement (auth robuste, anti-abus, surveillance).
- Performances de transcription et de rendu sur vidéos de plusieurs heures.

L'interface peut être gratuite et publique, mais **elle ne produira aucun montage tant qu'aucun moteur HTTPS n'est relié**.
