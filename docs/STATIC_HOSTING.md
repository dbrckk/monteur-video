# Site statique gratuit : Android en priorité

**Pour démarrer réellement le moteur V1 depuis un ordinateur avec HTTPS et une clé secrète générée automatiquement, lire [le guide Android + moteur gratuit](REMOTE_ANDROID.md).** Ce document précise aussi les scripts Linux/macOS et Windows, la reprise des rendus et la conservation des médias.

**Site principal gratuit en ligne et vérifié :** https://dbrckk.github.io/monteur-video/ (1 à 10 vidéos, choix de l'ordre et filtres après montage).

**Miroir gratuit :** https://snappy-gate-x58qpre.shipstatic.com

GitHub Pages est désormais activé et sert le dossier `web/` depuis GitHub Actions. Le workflow de publication vérifie automatiquement l'activation de Pages avant de déployer, afin de ne pas échouer lors d'une désactivation accidentelle. Le moteur distant HTTPS reste indispensable pour réellement traiter les vidéos.

## Utilisation sur smartphone

1. Ouvrir le site depuis Chrome Android, puis éventuellement **Ajouter à l'écran d'accueil** (PWA).
2. Renseigner l'URL HTTPS de son propre moteur de montage (une seule fois ; elle est mémorisée localement).
3. Saisir la clé du moteur, dans l'onglet actif uniquement. Elle n'est pas sauvegardée dans le stockage du navigateur.
4. Sélectionner **une à dix vidéos** depuis la galerie Android / le sélecteur de fichiers en une seule opération. L'ordre de sélection est conservé pour le montage commun. Choisir 9:16 / 16:9, thème et durée.
5. Garder **l'onglet ouvert pendant le transfert** : les fichiers sont envoyés **l'un après l'autre, en une seule opération de montage**, par blocs de 8 Mio, pour économiser la mémoire du téléphone. Android peut interrompre JavaScript lorsque l'écran est éteint ou le navigateur fermé.
6. En cas de rupture réseau, revenir sur le site, sélectionner **les mêmes fichiers dans le même ordre** (noms, tailles et dates de modification) puis relancer : chaque envoi reprend depuis l'octet confirmé par le serveur, sans repartir systématiquement à zéro.
7. Une fois le transfert intégralement terminé, **le traitement continue côté serveur**, indépendamment de l'onglet. Le dernier identifiant de montage est conservé sur le téléphone ; **Retrouver mon dernier montage** et ressaisir la clé au besoin.
8. **Après rendu**, une galerie de **filtres selon le thème** propose Original, Impact, Acier, Énergie, Cinéma, Soleil ou Noir & blanc. Les filtres conseillés sont présentés en premier. L'aperçu immédiat est une simulation CSS, à confirmer en lançant un véritable export FFmpeg. Le master original reste toujours conservé.
9. Utiliser **Télécharger le MP4 sur mon téléphone** pour enregistrer la version originale ou filtrée. Le navigateur Android gère son téléchargement habituel. Le ticket de téléchargement expire après 15 minutes ; l'interface renouvelle le lien au besoin.

**La reprise automatique n'est pas un upload en arrière-plan Android garanti.** Les navigateurs mobiles peuvent aussi libérer le fichier sélectionné lorsque la page est rechargée : il faut le sélectionner de nouveau.

## Architecture et sécurité

```text
Chrome Android -> hébergeur statique gratuit (GitHub Pages / ShipStatic)
       |
       +--- HTTPS / Authorization: Bearer ... ---> API FastAPI + FFmpeg + Whisper
                                                   sur PC ou machine avec stockage
       <--- lien MP4 signé temporaire --------------+
       |
       +--- téléchargement MP4 depuis l'API HTTPS
```

Le site statique n'héberge **ni fichiers sources, ni vidéos finales, ni moteur IA**. GitHub Pages n'exécute ni Python ni FFmpeg. Le traitement de vidéos de plusieurs Go nécessite CPU/RAM/disque et une machine accessible à distance. La disponibilité permanente d'un hébergement de calcul gratuit n'est pas garantie.

L'API accepte les requêtes depuis les origines explicites `https://dbrckk.github.io`, `https://angled-gate-srzt937.shipstatic.com` et `https://snappy-gate-x58qpre.shipstatic.com` (par défaut), plus les origines HTTPS déclarées avec `MONTEUR_CORS_ORIGINS`. Les requêtes sensibles exigent `APP_API_TOKEN`. En mode site statique, l'interface envoie le jeton dans l'en-tête Authorization pour chaque appel API, sans cookies tiers. Le téléchargement est autorisé par un **ticket HMAC signé à validité courte**, évitant de placer la clé API longue durée dans l'URL du MP4.

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

## Plusieurs vidéos et filtres : limites concrètes

- Jusqu'à **10 rushs par projet**, un montage final. Les données sont stockées sur le serveur de montage, pas chez l'hébergeur statique. Un fichier de plusieurs Go peut demander une connexion durable. Une répartition des extraits cherche à inclure chaque source ; la qualité artistique dépend toujours des images et du son présents.
- Un projet de montage est créé **de façon idempotente** avec un UUID conservé sur le téléphone. Une requête perdue au moment du lancement peut être rejouée sans produire deux montages.
- Les looks sont des **filtres prédéfinis FFmpeg** (pas une analyse esthétique par IA). L'utilisateur peut voir une simulation immédiatement ; un deuxième export vidéo est nécessaire pour télécharger le filtre réellement appliqué. L'original est conservé.
- Les filtres sont calculés par le même serveur que les montages. Si le serveur est éteint, aucune nouvelle variante ne peut être générée.
