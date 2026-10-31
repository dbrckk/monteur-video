# Workflow V6 gratuit de création de publicité UGC

**Pré-requis :** Python 3.10+, FFmpeg, FFprobe ; OpenCV+NumPy uniquement pour l'analyse visuelle optionnelle. Toutes les commandes ci-dessous travaillent sur les médias locaux. Aucun téléchargement de modèle ni token API.

## 1. Préparer un projet

Dans `examples/synthetic_demo.json`, les séquences parlées possèdent leur piste audio native. `sync: "native"` est obligatoire ; les photos produit peuvent être superposées pendant la parole sans la remplacer. Le moteur n'invente jamais l'horodatage des mots.

Les scènes finales doivent être de vraies créations autorisées : une démonstration technique ou des clips sans licence commerciale ne sont pas publiables. Le nom du produit et chaque caractéristique annoncée nécessitent des références.

## 2. Analyser avant de générer

```bash
python ugc.py check examples/synthetic_demo.json
python ugc.py editorial examples/synthetic_demo.json
python ugc.py assets examples/synthetic_demo.json
python ugc.py plan examples/synthetic_demo.json
```

`editorial` mesure le **temps de parole couvert par les inserts**, l'impact sur l'accroche et la fréquence des coupes. `assets` trie les sources par clarté mais ne reconnaît pas la marque.

## 3. Préparer un montage moins chargé

```bash
python ugc.py autoplan examples/synthetic_demo.json \
  --output examples/rose_mystik_demo_editorial_pass.json \
  --report examples/autoplan_report.json
```

L'original est préservé et le nouveau projet est créé dans le **même dossier** pour garder les chemins sécurisés. Les suggestions sont destinées à une validation humaine, notamment pour vérifier que chaque insert illustre correctement la phrase prononcée. Les choix trop chargés sont supprimés plutôt qu'exécutés de force.

Si vous souhaitez refuser tous les montages trop chargés, définissez `"editorial_policy": "required"`. Pour préserver la rétrocompatibilité V5, le défaut est `review`.

## 4. Produire et contrôler gratuitement

```bash
python ugc.py render examples/rose_mystik_demo_editorial_pass.json \
  --output UGC_V6_Demo_1080x1920.mp4
python ugc.py review UGC_V6_Demo_1080x1920.mp4 --output review_mobile.html
python ugc.py qa UGC_V6_Demo_1080x1920.mp4 --full-decode
```

Ouvrir `review_mobile.html` sur Android après avoir extrait l'archive avec le MP4 à proximité. Le navigateur utilise la vidéo locale et n'accède à aucun service externe.

Pour une vraie publicité, faire systématiquement une validation humaine complète des droits, du produit, de la prononciation française, des sous-titres et de l'alignement visuel des lèvres. Le moteur interdit toute publication automatique par défaut.

## 5. Tests importants

```bash
python functional_checks_v3.py
python functional_checks_v4.py
python functional_checks_v5.py
python functional_checks_v6.py
```

Le rendu de démo contient une mire **DEMO TECHNIQUE**, pas une influenceuse réaliste. Il vérifie le moteur et ses garde-fous, sans remplacer un test sur une vraie séquence UGC autorisée.

**Coûts API/génération :** 0. Les tests locaux utilisent CPU, stockage et électricité du serveur, jamais des crédits IA. Ne pas déclencher GitHub Actions ou un service cloud sans considérer ses propres quotas.
