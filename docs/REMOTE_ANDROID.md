# Monteur Studio V1 — utiliser le site depuis Android (gratuit)

**Interface officielle : https://dbrckk.github.io/monteur-video/**

L'interface est hébergée gratuitement et fonctionne dans Chrome Android. Le montage vidéo, l'analyse de la voix et les filtres utilisent **FFmpeg et, facultativement, faster-whisper sur un ordinateur qui vous appartient**. Il n'existe pas de calcul vidéo long hébergé gratuitement et garanti en permanence dans cette installation.

## Préparation de l'ordinateur

- Un ordinateur Windows, Linux ou macOS qui reste **allumé** durant l'import et les rendus. Le montage ne consomme pas la puissance du smartphone.
- **Docker Desktop** installé sur Windows/macOS (ou Docker Engine + Compose v2 sur Linux) ; suffisamment d'espace disque libre pour les rushs, les segments temporaires et les exports.
- Connexion Internet sur le PC et le smartphone, sans port entrant à ouvrir sur votre box.
- Dépôt : https://github.com/dbrckk/monteur-video

Ouvrez un terminal sur le PC. Clonez une seule fois le dépôt :

```bash
git clone https://github.com/dbrckk/monteur-video.git
cd monteur-video
```

Sur **Linux/macOS** :

```bash
bash scripts/start-free.sh
```

Sur **Windows**, depuis PowerShell dans le répertoire du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-free.ps1
```

Ces scripts génèrent automatiquement une **clé privée aléatoire**, la conservent dans le fichier local `.env`, démarrent Docker et ouvrent un **Cloudflare Quick Tunnel** gratuit. Ils affichent dans le terminal trois informations :

1. Site Android : `https://dbrckk.github.io/monteur-video/`
2. Adresse HTTPS du moteur : `https://quelque-chose.trycloudflare.com` (exemple, votre adresse réelle est différente)
3. Clé privée `APP_API_TOKEN`.

**La clé ne doit pas être envoyée à d'autres personnes ni publiée dans GitHub.** Le fichier `.env` est ignoré par Git et doit rester sur le PC.

### Sur le smartphone

1. Ouvrez le site officiel dans Chrome Android. Vous pouvez l'ajouter à l'écran d'accueil.
2. Collez l'adresse HTTPS du moteur affichée par le PC dans « Adresse HTTPS du moteur de montage », puis touchez **Enregistrer le moteur**.
3. Saisissez la clé privée dans le champ prévu et utilisez **Vérifier la connexion du moteur**. Un message indique alors la version V1, l'espace disque disponible et la durée de conservation.
4. Sélectionnez **1 à 10 vidéos en une seule fois** depuis le téléphone. Modifiez si besoin leur ordre avec les flèches ↑/↓, choisissez le thème et le format (9:16 Instagram ou 16:9 YouTube).
5. Appuyez sur **Créer mon montage**. Les fichiers sont transférés *l'un après l'autre par blocs de 8 Mio*, avec reprise d'envoi si le réseau s'interrompt. **Gardez l'onglet ouvert pendant l'envoi.** Si la page est rechargée, choisissez à nouveau les mêmes fichiers dans le même ordre pour reprendre.
6. Une fois l'envoi terminé, vous pouvez fermer l'onglet : le montage continue sur le PC. La progression est mémorisée côté serveur et le dernier identifiant de montage est conservé dans le navigateur.
7. Retrouvez le résultat avec **Retrouver mon dernier montage**, prévisualisez-le, choisissez éventuellement un filtre recommandé et appuyez sur **Appliquer** pour lancer l'export filtré.
8. **Télécharger le MP4 sur mon téléphone** sauvegarde la version sélectionnée. Les liens sont signés et renouvelés lorsque nécessaire. Vous pouvez ensuite supprimer toutes les vidéos du serveur avec le bouton prévu.

Si un rendu échoue, **Relancer le rendu sans renvoyer les vidéos** retente le montage depuis les rushs enregistrés, tant qu'ils sont encore disponibles. Après redémarrage du PC, les montages interrompus sont remis en file d'attente automatiquement.

## Accès distant gratuit avec URL stable (recommandé)

Cloudflare Quick Tunnels ne garantit ni disponibilité permanente, ni conservation de l'URL après redémarrage : c'est un service destiné aux tests. Pour conserver la même adresse HTTPS entre redémarrages, **Tailscale Funnel** permet un domaine stable `*.ts.net`, disponible sur le plan Personal gratuit.

Installez [Tailscale](https://tailscale.com/download) sur le PC, connectez-vous au compte Tailscale, puis lancez sur Linux/macOS :

```bash
bash scripts/start-stable.sh
```

La première fois, Tailscale peut demander une approbation d'activation de Funnel via le navigateur. Le script lance Docker, publie le moteur sur un nom HTTPS stable puis affiche le domaine à saisir sur le smartphone. **Le PC doit rester sous tension, connecté à Tailscale et exécuter Docker.**

Sur Windows, vous pouvez conserver le même fichier `.env` et démarrer le moteur avec `docker compose up --build -d`, puis exécuter `tailscale funnel --bg 8000` dans PowerShell (Tailscale doit être installé et connecté). La commande `tailscale funnel status` affiche l'URL publique.

Tailscale Funnel est disponible sur les offres gratuites, mais impose des limites de bande passante et une configuration initiale du réseau Tailscale. Ce mode est plus pratique pour retrouver le moteur à la même adresse ; il ne remplace pas un serveur toujours allumé. N'utilisez pas les deux tunnels si vous n'en avez pas besoin.

Sources : [documentation Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) et [documentation Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel).

## Données, capacité et fonctionnement

**Tous les MP4 et rushs résident sur le disque du PC qui héberge Docker.** Le site statique GitHub Pages n'enregistre pas vos vidéos. Les accès Internet au moteur exigent la clé API forte ; les URLs de téléchargement sont signées et n'exposent pas cette clé.

Par défaut :

- Jusqu'à **10 vidéos** par montage ; jusqu'à **20 Gio par source** (configurable).
- **72 heures** de conservation pour un envoi abandonné ; **14 jours** pour un montage terminé ou échoué. Ces délais se règlent avec `UPLOAD_TTL_HOURS` et `RESULT_TTL_DAYS` dans `.env`. Le serveur nettoie les fichiers périmés au démarrage puis périodiquement.
- Un seul rendu/filtre exécuté à la fois pour éviter la saturation mémoire. Les autres sont mis en file d'attente SQLite.
- Le format final est H.264/AAC en MP4 avec `faststart`, adapté au téléchargement et à la lecture sur les téléphones Android.
- Le Dockerfile installe faster-whisper par défaut pour la transcription CPU ; au premier rendu vocal, le modèle peut nécessiter un téléchargement initial. **Le modèle est mis en cache dans le volume Docker persistant** (`/data/huggingface`) et n'est pas retéléchargé lors des reconstructions ordinaires de l'image. Pour désactiver cette option et alléger le déploiement, ajoutez `INSTALL_WHISPER=0` dans `.env` puis reconstruisez Docker. Le montage reste fonctionnel sans sous-titres automatiques.

Attention : le rendu de vidéos très longues exige du **temps CPU, de la mémoire et beaucoup d'espace disque**. La connexion mobile peut ralentir les envois ; il est conseillé d'utiliser le Wi-Fi et l'alimentation secteur. **Android ne garantit pas les téléchargements vers un site lorsque Chrome est fermé ou suspendu**, même si les envois peuvent être repris en resélectionnant les fichiers.

## Vérification et dépannage

Sur le PC :

```bash
docker compose ps
docker compose logs --tail=100 monteur
curl http://127.0.0.1:8000/api/health
```

Avec Quick Tunnel :

```bash
docker compose -f compose.yaml -f compose.remote.yaml logs --tail=100 tunnel
```

Les causes fréquentes sont un Docker non démarré, un PC en veille, un disque plein, une mauvaise clé API ou l'utilisation d'une ancienne adresse Quick Tunnel. Si le PC redémarre, récupérez l'URL actuelle depuis les logs, puis actualisez « Adresse HTTPS du moteur » sur le téléphone.

Pour arrêter volontairement Quick Tunnel et le moteur :

```bash
docker compose -f compose.yaml -f compose.remote.yaml down
```

**N'ajoutez pas `-v` à cette commande** si vous souhaitez conserver le volume Docker contenant les rushs et les projets. Ne publiez jamais un port 8000 non protégé sur Internet.

## État de validation

Le projet possède des tests CI pour les imports HTTP par blocs, la fusion réelle de plusieurs vidéos, les sorties verticales/horizontales, les variantes FFmpeg, les liens signés, les reprises après redémarrage et les nettoyages automatiques. Un second workflow construit et démarre un conteneur Docker réel dans sa variante légère.

Ce contrôle automatique ne remplace pas un essai complet sur un **vrai Android** et la connexion réelle à votre propre PC via Cloudflare/Tailscale : ces deux éléments demandent un équipement connecté, qui ne peut pas être créé par GitHub Pages.
