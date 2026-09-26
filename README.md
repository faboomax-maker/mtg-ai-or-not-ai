# Vraie ou IA ? — le quiz Magic

Un quiz web : chaque carte est soit une **vraie carte Magic**, soit une carte **inventée par une IA** (texte et illustration). Le joueur doit deviner laquelle.

Toutes les cartes passent par **le même rendu** : [Magic Set Editor](https://github.com/twanvl/MagicSetEditor2) les dessine avec le même cadre M15 (templates du [Full Magic Pack](https://github.com/MagicSetEditorPacks/Full-Magic-Pack)), illustrations recadrées à l'identique, symbole de set dessiné pareil, fichiers renommés au hasard. Seul le contenu peut trahir une carte.

```
Scryfall (gratuit) ──► vraies cartes : texte + « art crop »  ─┐
                                                             ├─► render_mse.py (Magic Set Editor) ─► build.py ─► docs/
LLM (texte) + FLUX (image) ──► cartes IA                     ─┘
```

## Mise en ligne sur GitHub Pages

1. Crée un dépôt et pousse ce dossier :
   ```bash
   git init && git add . && git commit -m "Quiz Vraie ou IA"
   git branch -M main
   git remote add origin https://github.com/<toi>/<depot>.git
   git push -u origin main
   ```
2. Sur GitHub : **Settings → Pages → Build and deployment → Deploy from a branch**, branche `main`, dossier **`/docs`**.
3. Le site est en ligne sur `https://<toi>.github.io/<depot>/`, d'abord avec un **petit jeu de démo** (12 cartes, illustrations provisoires).

## Générer les vraies données

### Option A — directement sur GitHub (rien à installer)

1. **Settings → Secrets and variables → Actions → New repository secret** :
   - `OPENAI_API_KEY` : suffit pour le texte **et** les illustrations (réglages par défaut du workflow)
   - ou `ANTHROPIC_API_KEY` (texte, `llm = anthropic`), `LLM_API_KEY` pour une autre API compatible OpenAI (OpenRouter…),
     `REPLICATE_API_TOKEN` (illustrations FLUX schnell, `images = replicate`)
2. Onglet **Actions → « Générer les cartes » → Run workflow**, puis choisis le nombre de cartes et les fournisseurs.
3. Le workflow génère tout, commite `docs/` et Pages se met à jour tout seul.

### Option B — en local

```bash
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt

python pipeline/fetch_real.py --count 60                # 1. vraies cartes (Scryfall, gratuit)

export ANTHROPIC_API_KEY=...  REPLICATE_API_TOKEN=...
python pipeline/generate_fake.py --count 60             # 2. cartes IA

powershell -ExecutionPolicy Bypass -File pipeline/setup_mse.ps1   # une fois : MSE + polices (Windows)
python pipeline/render_mse.py                           # 3. rendu des cartes avec MSE
python pipeline/build.py                                # 4. assemble docs/
python -m http.server -d docs 8000                      # aperçu sur http://localhost:8000
```

Les scripts **reprennent là où ils se sont arrêtés** : relancer une commande complète le lot sans rien regénérer.

## Coût par carte IA

| Poste | Option | Coût approximatif |
|---|---|---|
| Texte | Claude Haiku 4.5 (`--llm anthropic`), lots de 8 cartes | ~0,002 $ |
| Texte | Ollama en local (`--llm openai`, `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=llama3.1`) | 0 $ |
| Image | FLUX schnell sur Replicate (`--images replicate`) | ~0,003 $ |
| Image | Pollinations (`--images pollinations`, clé optionnelle `POLLINATIONS_KEY`) | gratuit ou quasi |
| Vraies cartes | API Scryfall | 0 $ |

**Environ 0,5 centime par carte IA**, soit ~0,30 $ pour un quiz de 120 cartes (60 + 60). Tarifs indicatifs, à vérifier chez chaque fournisseur.

Autres modes utiles : `--images placeholder` (dégradés, pour tester gratuitement) et `--images none` (tu déposes tes propres images dans `pipeline/work/img/fake_<id>.jpg`, par exemple générées en local avec ComfyUI ou Forge).

## Ce qui rend les fausses cartes crédibles

- **Même profil que les vraies** : chaque carte IA reprend les couleurs, le type, la rareté, la valeur de mana et la présence ou non de flavor text d'une vraie carte. Les deux pools ont donc la même distribution.
- **Vrais symboles de set** : les vraies cartes affichent le symbole de leur extension (police [Keyrune](https://keyrune.andrewgioia.com)), coloré selon la rareté. Les extensions absentes de Keyrune sont ignorées. Chaque carte IA est « rangée » dans une extension des vraies cartes, avec la même répartition, et reçoit son symbole.
- **Cohérence avec le set** : le prompt de chaque carte IA contient 10 vraies cartes *de la même extension*, pour reprendre ses mécaniques, types de créatures, factions et univers, ainsi que le templating Oracle et le niveau de puissance. Un symbole Bloomburrow sur une carte sans animaux ne trahira donc personne. Ces exemples ne sont jamais montrés dans le quiz.
- **Fiche de l'extension** : pour chaque extension, le modèle de texte rédige une fois une fiche (univers, mécaniques phares, direction artistique), à partir du nom, de l'année et des mots-clés les plus fréquents du set. Elle sert au prompt des cartes **et** à celui des illustrations, avec l'année de sortie.
- **Ligne du bas comme sur les vraies cartes** : numéro de collection (format `100/281 C` avant mars 2023, `C 0100` ensuite), code du set, `EN`, illustrateur et `™ & © <année> Wizards of the Coast`. Les cartes IA reçoivent un numéro libre du set et un **illustrateur inventé**, vérifié absent de la liste des artistes Magic de Scryfall : aucune image IA n'est attribuée à un vrai artiste.
- **Mots de capacité en italique** (*Landfall* —, *Valiant* —…), comme à l'impression.
- **Honnêteté à la révélation** : après la réponse, une carte IA indique que son symbole de set a été emprunté.
- **Filtres** : coût de mana valide, force/endurance présentes, longueur raisonnable, et **nom vérifié inexistant** sur Scryfall.
- **Même époque** : vraies cartes au cadre moderne (depuis 2016), sans Universes Beyond, rééditions ni cartes Un-.
- **Artiste et extension masqués** pendant la question, révélés seulement après la réponse.

Réglages : modèle via `LLM_MODEL`, requête Scryfall via `--query` (par exemple `--query "set:dsk -type:basic"` pour un quiz sur une seule extension), style d'image via `ART_STYLE` dans `generate_fake.py`.

## Structure

```
docs/                 site statique publié par GitHub Pages
  index.html  style.css  app.js
  data/cards.json     cartes (réponse légèrement obfusquée)
  img/                cartes rendues par MSE (WebP, noms aléatoires)
pipeline/
  fetch_real.py       1. vraies cartes depuis Scryfall
  generate_fake.py    2. cartes IA (texte + image)
  render_mse.py       3. rendu des cartes avec Magic Set Editor (cadre M15, symboles Keyrune)
  setup_mse.ps1       installe MSE (Full Magic Pack, templates M15) et ses polices
  build.py            4. fusion, mélange, export vers docs/
  demo.py             jeu de démo hors ligne
  common.py  placeholder.py
.github/workflows/generate.yml   génération à la demande sur GitHub
```

## Limites connues

- La réponse est seulement **obfusquée** dans `cards.json` : un joueur qui fouille le code peut tricher. C'est un jeu entre amis, pas un examen.
- Les cartes sont en anglais : c'est la langue de référence de Scryfall et des modèles.
- Le rendu demande Windows (Magic Set Editor) : le workflow GitHub tourne donc sur un runner Windows.
- Sans ender_mse.py, uild.py retombe sur l'ancien cadre HTML/CSS.

## Crédits et licences

Données et illustrations des vraies cartes : [Scryfall](https://scryfall.com). L'artiste est affiché après chaque réponse. Merci de respecter leurs [conditions d'utilisation de l'API](https://scryfall.com/docs/api) : pas plus de 10 requêtes par seconde, projet gratuit et sans paywall.

Contenu de fan non officiel, autorisé par la [Fan Content Policy](https://company.wizards.com/fancontentpolicy). Non approuvé par Wizards. Des parties des éléments utilisés sont la propriété de Wizards of the Coast. ©Wizards of the Coast LLC.
