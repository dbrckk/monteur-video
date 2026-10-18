# Monteur Studio V1 — moteur HTTPS gratuit depuis un ordinateur

L'interface Android est publique sur **https://dbrckk.github.io/monteur-video/**.
Pour traiter réellement des vidéos longues sans payer un hébergeur, un ordinateur
disposant de Docker, de stockage et d'une connexion internet sert de moteur
FFmpeg/Whisper. Un tunnel HTTPS Cloudflare Quick Tunnel publie **uniquement**
l'API de cet ordinateur. La clé API reste obligatoire.

## Démarrage

```bash
git clone https://github.com/dbrckk/monteur-video.git
cd monteur-video
bash scripts/start-public.sh
```

La commande génère une clé aléatoire de 64 caractères hexadécimaux dans `.env`
avec permissions 0600, démarre le moteur et le tunnel. La première construction
Docker télécharge FFmpeg et, par défaut, les dépendances de transcription
Whisper ; elle peut être longue. Sur machine peu puissante, mettre
`INSTALL_WHISPER=0` dans `.env` pour un montage sans transcription.

Afficher l'URL HTTPS active :

```bash
docker compose -f compose.yaml -f compose.public.yaml logs --tail=80 tunnel
```

Chercher l'URL `https://....trycloudflare.com`, puis la saisir sur le site
dans **Adresse du moteur HTTPS**. Copier la valeur de `APP_API_TOKEN`
depuis `.env` dans **Clé d'accès**. Ne pas communiquer cette clé.

Choisir une à dix vidéos depuis Android. Les fichiers transitent vers votre
ordinateur par HTTPS et sont conservés sur le volume Docker `montages`.
Le téléphone doit garder la page active pendant les transferts ; le PC
effectue le montage après réception et peut poursuivre même si le téléphone
est verrouillé. Revenir dans la page pour consulter le montage, choisir
un filtre et télécharger la version finale.

## Limites et fiabilité

- Le tunnel Quick Tunnel est **gratuit mais temporaire** : l'URL change après
  un redémarrage, sans garantie de disponibilité ni de débit, et des limites
  de service peuvent s'appliquer. Les transferts de plusieurs Go ne sont
  pas garantis ; les uploads sont découpés et reprenables lorsque l'API et
  ses données persistent.
- La machine doit rester allumée, connectée, avec suffisamment de disque
  pour les rushs, les rendus intermédiaires et les filtres.
- Le site GitHub Pages n'héberge **aucun calcul vidéo**. Il ne peut pas
  fonctionner seul pour monter une longue vidéo.
- L'API est protégée par une clé partagée ; toute personne connaissant la
  clé peut accéder aux projets. Le site ne conserve pas cette clé sur disque.
  Utiliser une installation personnelle, ne jamais publier `.env`.
- Pour un domaine permanent et un tunnel plus robuste, configurer un tunnel
  Cloudflare nommé avec votre domaine ; cela requiert des paramètres
  supplémentaires. Le mode Quick Tunnel évite tout achat de domaine.
- Le montage est séquentiel côté moteur, pour ne pas saturer CPU et mémoire.
  Le stockage et la transcription dépendent de votre machine.

## Arrêt

```bash
docker compose -f compose.yaml -f compose.public.yaml --profile public down
```

Le volume `montages` est conservé par défaut. **Ne pas utiliser `down -v`**
si vous souhaitez retrouver les vidéos et projets.
