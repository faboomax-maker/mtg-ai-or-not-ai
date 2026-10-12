# Mini-jeux Magic

Une petite collection de jeux web autour de Magic, publiée sur GitHub Pages. En ouvrant le site, on choisit son jeu :

| Jeu | Dossier | En deux mots |
|---|---|---|
| **Carte bannie ?** (nouveau) | `docs/games/bannies/` | Une carte (cadre moderne) : bannie en Modern, en Legacy, en Duel Commander, ou nulle part ? La moitié sont des leurres légaux qui ont l'air bannis. |
| **Est-ce légal ?** (nouveau) | `docs/games/legal/` | Des situations de jeu dessinées avec les vraies cartes : le coup tenté est-il permis par les règles ? Mode facile (classiques) et difficile (couches, dépendances, actions spéciales, coûts « sans payer »), avec des questions à choix sur le résultat. Explication et règle citée à chaque réponse. |
| **Carte mystère** | `docs/games/mystere/` | Une carte par jour, cachée lettre par lettre (façon Spellify) : lettres, chiffres et symboles de mana se révèlent partout sur la carte ; 13 essais pour trouver son nom. Statistiques et série, partage du résultat. |
| **Plus cher ou moins cher ?** | `docs/games/plus-cher/` | Une carte et son prix : la suivante vaut-elle plus ou moins ? Variante **Plus ou moins populaire ?** (classement EDHREC), accessible par un bouton en bas de l'accueil du jeu. Quatre difficultés à débloquer par variante, record par mode. |
| **Quelle guilde es-tu ?** | `docs/games/guildes/` | Quiz de personnalité : découvre ta guilde de Ravnica, avec son blason et ton profil de personnalité. |
| **IA ou vraie carte ?** | `docs/games/ia-ou-vraie/` | Vraie carte ou carte inventée par une IA ? Mode facile, hardcore et classement. |

Chaque jeu a son lien direct : `https://<toi>.github.io/<depot>/#guildes`, `…/#ia-ou-vraie`.

### Ajouter un jeu

1. Crée `docs/games/<id>/` avec un `game.js` (et un `style.css` si besoin).
2. Dans `game.js`, enregistre le jeu : `window.MTG.games.push({ id, title, pitch, icon, details, isNew, component })`. `component` est un composant React qui reçoit `onExit` (retour à l'accueil) ; `icon` est un nom d'icône Artifice (`d20`, `chalice`, `potion`…).
3. Ajoute ses `<script>` et `<link>` dans `docs/index.html`, après `app.js`.

Le badge « Nouveau » s'affiche tant que `isNew: true` ; le jeu est alors présenté en premier.

### Cartes de « Carte mystère »

`docs/data/mystere.json` est un programme {date (heure de Paris) : carte} de la veille à 3 semaines, écrit par `pipeline/mystere.py` pendant le même workflow quotidien que les prix. Une date déjà programmée garde sa carte, et une carte déjà sortie ne revient pas avant que toutes les autres soient passées. Cartes possibles : simple face, parmi les 1 500 plus jouées en Commander, sans symboles exotiques (hybrides, phyrexians…). Les cartes sont légèrement scellées dans le fichier pour ne pas se lire d'un coup d'œil.

Juste après, le workflow Windows **« Rendre les cartes mystère »** (`.github/workflows/mystere.yml`, lancé automatiquement à la fin de la mise à jour des prix, ou à la main) rend la carte du lendemain (et celle du jour si elle manque) avec Magic Set Editor, au cadre M15 du quiz : une version **vide** (cadre, illustration floutée, symbole d'extension, sans nom, coût, type, texte ni F/E) et la version **complète**, dans `docs/img/mystere/` (`pipeline/render_mystere.py`). Pendant la partie, le jeu pose le texte caché sur la version vide, aux emplacements du cadre (boîtes `.my-box--*` dans `docs/games/mystere/style.css` ; ajouter `?boxes` à l'adresse du site pour les voir) ; à la fin, il affiche la vraie carte. Une carte que MSE n'a pas pu rendre garde le cadre HTML du jeu.

### Situations de « Est-ce légal ? »

Les situations sont dans `docs/games/legal/scenarios.json` (champ `mode` : `facile` ou `difficile` ; `type: choice` pour une question à choix, avec `question`, `options` et `answer`) : le plateau (cartes de chaque joueur, pile, cimetière, main, exil, zone de commandement, phase, mana disponible), le coup tenté, la réponse et son explication. Chaque carte utilisée a des règles de vérification (`checks`) : le workflow quotidien les compare au texte Oracle de Scryfall (`pipeline/legal_check.py`) et écrit `docs/data/legal-cards.json`. Une situation dont une carte ne correspond plus (texte Oracle modifié par Wizards) n'est plus proposée, et le log du workflow dit laquelle. `?s=<id>` dans l'adresse joue une seule situation.

### Listes de « Carte bannie ? »

`docs/data/bannies.json` vient des légalités de Scryfall (Modern, Legacy, Duel Commander), mises à jour par le même workflow quotidien (`pipeline/bannies.py`) : la réponse suit chaque annonce de bannissement dès le lendemain. Seules les cartes au cadre moderne (2003 ou 2015) et légales ou bannies dans les trois formats sont gardées. Les leurres sont des cartes légales dans les trois formats, de quatre sortes, prises à tour de rôle : **anciennes cartes bannies** (historique `docs/data/bannies-history.json`, enrichi chaque jour de toute carte vue bannie, amorcé avec des débannissements célèbres), **bannies ailleurs** (Commander, Pioneer, Standard, Pauper, restreintes en Vintage…), **cousines** (même mécanique qu'une carte bannie : delve, cascade, « sans payer son coût »…) et **suspectes** (très jouées, chères, peu coûteuses…). Après la réponse, le jeu dit pourquoi c'était un piège. Chaque partie mélange 5 à 7 cartes bannies, celles bannies dans un ou deux formats seulement étant deux fois plus probables.

### Prix de « Plus cher ou moins cher ? »

`docs/data/prix.json` vient des données gratuites de Scryfall (prix Cardmarket tendance, en euros, et popularité EDHREC). Le workflow **« Mettre à jour les prix »** le régénère chaque nuit (vers 6 h, heure de Paris) ; on peut aussi le lancer à la main (onglet **Actions → Mettre à jour les prix → Run workflow**), ou en local : `python pipeline/fetch_prices.py`.

Difficultés (réglables dans `VARIANTS`, en haut de `docs/games/plus-cher/game.js`). Chaque mode se débloque en faisant une série de 5 dans le précédent (`UNLOCK`). Pour les prix :

| Mode | Cartes | Écart de prix |
|---|---|---|
| Facile | les 2 500 plus jouées en Commander | ×3 à ×30 |
| Moyen | les 12 000 plus jouées | ×1,6 à ×3 |
| Hardcore | hors des 3 000 plus jouées, ou non classées | ×1,6 à ×3 |
| Impossible | hors des 3 000 plus jouées, ou non classées | ×1,15 à ×1,6 |

Pour la popularité (rang EDHREC, cartes classées uniquement) :

| Mode | Cartes | Écart de rang |
|---|---|---|
| Facile | les 3 000 plus jouées | ×4 à ×60 |
| Moyen | les 12 000 plus jouées | ×2 à ×4 |
| Hardcore | au-delà du rang 3 000 | ×2 à ×4 |
| Impossible | au-delà du rang 3 000 | ×1,15 à ×1,6 |

## IA ou vraie carte ?

Chaque carte est soit une **vraie carte Magic**, soit une carte **inventée par une IA** (texte et illustration). Le joueur doit deviner laquelle.

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

Chaque carte IA passe par : **3 appels texte** par lot de 8 cartes (conception, relecture Play Design, relecture Creative), une **fiche par extension** (une fois par set), puis **1 à 3 illustrations** (chacune vérifiée par le modèle texte, qui voit l'image, et refaite si elle a un défaut). Les cartes rejetées par les contrôles sont redemandées, d'où une marge d'environ ×1,5 sur le texte.

| Poste | Option | Coût par carte IA |
|---|---|---|
| Texte (3 passes + marge des rejets) | gpt-4.1-mini (0,40 $ / 1,60 $ par million de jetons) | ~0,002 $ |
| Vérification de l'image | même modèle, image en basse définition | ~0,0003 $ par image |
| Illustration | FLUX 1.1 Pro sur Replicate (`REPLICATE_MODEL=black-forest-labs/flux-1.1-pro`) : 0,04 $ × 1,2 à 1,5 essai | ~0,05–0,06 $ |
| Illustration | FLUX schnell (défaut) : 0,003 $ × essais | ~0,004 $ |
| Vraies cartes, symboles, rendu MSE, GitHub Actions | Scryfall, MTGJSON, Keyrune, Magic Set Editor, runner GitHub (dépôt public) | 0 $ |

**≈ 0,05–0,06 $ par carte IA avec FLUX 1.1 Pro**, soit **~3–4 $ pour un quiz de 120 cartes** (60 vraies + 60 IA). L'image représente ~95 % du coût. Pire cas (3 essais d'image par carte) : ~0,12 $ par carte. `ART_TRIES=1` désactive la vérification des images (1 seule image par carte). Tarifs indicatifs de septembre 2026, à vérifier chez chaque fournisseur.

Autres modes utiles : `--images placeholder` (dégradés, pour tester gratuitement) et `--images none` (tu déposes tes propres images dans `pipeline/work/img/fake_<id>.jpg`, par exemple générées en local avec ComfyUI ou Forge).

## Ce qui rend les fausses cartes crédibles

- **Peu de rares et de mythiques** : ce sont les cartes que les joueurs connaissent par cœur (une vraie mythique se reconnaît, une fausse aussi). Les deux pools sont tirés avec les mêmes poids : 55 % communes, 40 % peu communes, 4 % rares, 1 % mythiques. Réglable avec la variable GitHub `RARITY_WEIGHTS` (ex. `common=70,uncommon=30,rare=0,mythic=0`) ou l'option `--rarity-weights`.
- **Vraies illustrations** (`ART_SOURCE=real`, défaut) : chaque carte IA reprend l'illustration de la vraie carte dont elle copie le profil (même set, couleurs, type), de préférence une carte peu jouée (rang EDHREC) et jamais une carte du quiz. Le modèle texte voit une description de l'image et écrit nom, types, texte et ambiance en accord avec elle. L'artiste réel est crédité, et la révélation indique de quelle carte vient l'illustration. Le quiz porte alors sur le texte. `ART_SOURCE=generate` revient aux illustrations générées.
- **Même profil que les vraies** : chaque carte IA reprend les couleurs, le type, la rareté, la valeur de mana et la présence ou non de flavor text d'une vraie carte. Les deux pools ont donc la même distribution.
- **Vrais symboles de set** : les vraies cartes affichent le symbole de leur extension (police [Keyrune](https://keyrune.andrewgioia.com)), coloré selon la rareté. Les extensions absentes de Keyrune sont ignorées. Chaque carte IA est « rangée » dans une extension des vraies cartes, avec la même répartition, et reçoit son symbole.
- **Cohérence avec le set** : le prompt de chaque carte IA contient 10 vraies cartes *de la même extension*, pour reprendre ses mécaniques, types de créatures, factions et univers, ainsi que le templating Oracle et le niveau de puissance. Un symbole Bloomburrow sur une carte sans animaux ne trahira donc personne. Ces exemples ne sont jamais montrés dans le quiz.
- **Fiche de l'extension** : pour chaque extension, le modèle de texte rédige une fois une fiche (univers, mécaniques phares, direction artistique), à partir du nom, de l'année et des mots-clés les plus fréquents du set. Elle sert au prompt des cartes **et** à celui des illustrations, avec l'année de sortie.
- **Ligne du bas comme sur les vraies cartes** : numéro de collection (format `100/281 C` avant mars 2023, `C 0100` ensuite), code du set, `EN`, illustrateur et `™ & © <année> Wizards of the Coast`. Les cartes IA reçoivent un numéro libre du set et un **illustrateur inventé**, vérifié absent de la liste des artistes Magic de Scryfall : aucune image IA n'est attribuée à un vrai artiste.
- **Corrigé d'après les vraies cartes du set** (`pipeline/realism.py`) : textes de rappel remplacés par ceux réellement imprimés dans le set (ou supprimés s'ils sont inconnus), formulation de l'époque (« enters the battlefield » / nom de la carte, ou « enters » / « this creature » depuis 2024), mots-clés imposés par le profil de la vraie carte copiée, types de créatures du set, numéro de collection dans la plage de sa couleur (le set est numéroté W, U, B, R, G, multicolore, artefacts, terrains), nom d'illustrateur ordinaire et jamais répété.
- **Relecture « Play Design »** : un second appel au modèle relit chaque lot comme l'équipe de développement de Wizards, en comparant chaque carte à 3 vraies cartes du set (même rareté, type, couleurs, coût proches) : niveau de puissance, **équilibre des modes** (aucun mode évidemment meilleur), rares assez riches, actions-mots-clés bien employées.
- **Rejets automatiques** : action-mot-clé écrite comme une capacité (« Connive 1 »), rare en une ligne, nom réutilisant un mot d'une autre carte IA ou un mot surexploité par les IA (Insight, Whisperer, Echo…), description d'illustration clichée (silhouette encapuchonnée, vue de dos…). Les adjectifs « glowing / luminous / ethereal » sont retirés des descriptions, et « You draw » devient « Draw ».
- **Illustrations guidées par les vraies** : avec un modèle d'image qui accepte des images de référence (`black-forest-labs/flux-2-pro`, `google/nano-banana-pro`, `bytedance/seedream-4`), chaque illustration IA reçoit 3 vraies illustrations du même set (couleurs et type proches, 3 artistes différents) comme références de style — technique, palette, lumière — sans en copier le sujet. Le prompt commence par le sujet tiré de la ligne de type (« a Human Soldier — an ordinary human being… »), et la vérification visuelle refait l'image si la créature ne correspond pas.
- **Moins « poli IA »** : chaque illustration reçoit aussi 1 tableau du domaine public (Waterhouse, Leighton, Bierstadt, Friedrich, John Martin, Turner, Gérôme, Uccello, John Bauer… via Wikimedia Commons), choisi selon le sujet, pour imiter une touche de peinture libre ; le style demande des bords doux, un arrière-plan moins fini, pas de rendu uniformément net. Variable `STYLE_REFS` : `mix` (défaut : 2 vraies illustrations du set + 1 tableau), `set` (3 vraies illustrations), `classic` (le tableau seul).
- **Mots de capacité en italique** (*Landfall* —, *Valiant* —…), comme à l'impression.
- **Honnêteté à la révélation** : après la réponse, une carte IA indique que son symbole de set a été emprunté.
- **Filtres** : coût de mana valide, force/endurance présentes, longueur raisonnable, et **nom vérifié inexistant** sur Scryfall.
- **Même époque** : vraies cartes au cadre moderne (depuis 2016), sans Universes Beyond, rééditions ni cartes Un-.
- **Artiste et extension masqués** pendant la question, révélés seulement après la réponse.

Réglages : modèle via `LLM_MODEL`, requête Scryfall via `--query` (par exemple `--query "set:dsk -type:basic"` pour un quiz sur une seule extension), style d'image via `ART_STYLE` dans `generate_fake.py`.

## Structure

```
docs/                 site statique publié par GitHub Pages
  index.html          charge l'accueil puis chaque jeu
  app.js  style.css   accueil (choix du jeu, lien #<id>) et mise en page commune
  games/
    ia-ou-vraie/      game.js, style.css : le quiz « IA ou vraie carte ? »
    guildes/          data.js (questions, barème, guildes), game.js, style.css
    plus-cher/        game.js, style.css : « Plus cher ou moins cher ? »
    mystere/          game.js, style.css : « Carte mystère »
    legal/            scenarios.json, game.js, style.css : « Est-ce légal ? »
    bannies/          game.js, style.css : « Carte bannie ? »
  data/prix.json      prix des cartes (pipeline/fetch_prices.py, chaque jour)
  data/mystere.json   cartes du jour de « Carte mystère » (pipeline/mystere.py, chaque jour)
  data/cards.json     cartes du quiz IA (réponse légèrement obfusquée)
  img/                cartes rendues par MSE (WebP, noms aléatoires)
pipeline/
  fetch_real.py       1. vraies cartes depuis Scryfall
  generate_fake.py    2. cartes IA (texte + image)
  render_mse.py       3. rendu des cartes avec Magic Set Editor (cadre M15, symboles Keyrune)
  setup_mse.ps1       installe MSE (Full Magic Pack, templates M15) et ses polices
  build.py            4. fusion, mélange, export vers docs/
  fetch_prices.py     prix Scryfall pour « Plus cher ou moins cher ? » (+ cartes du jour)
  mystere.py          cartes du jour de « Carte mystère »
  legal_check.py      vérification Oracle des cartes de « Est-ce légal ? »
  bannies.py          listes de bannissement pour « Carte bannie ? »
  render_mystere.py   rendu MSE des cartes du jour (version vide + complète)
  demo.py             jeu de démo hors ligne
  common.py  placeholder.py
.github/workflows/generate.yml   génération à la demande sur GitHub
```

## Limites connues

- La réponse est seulement **obfusquée** dans `cards.json` : un joueur qui fouille le code peut tricher. C'est un jeu entre amis, pas un examen.
- Les cartes sont en anglais : c'est la langue de référence de Scryfall et des modèles.
- Le rendu demande Windows (Magic Set Editor) : le workflow GitHub tourne donc sur un runner Windows.
- Sans 
ender_mse.py, uild.py retombe sur l'ancien cadre HTML/CSS.

## Crédits et licences

Données et illustrations des vraies cartes : [Scryfall](https://scryfall.com). L'artiste est affiché après chaque réponse. Merci de respecter leurs [conditions d'utilisation de l'API](https://scryfall.com/docs/api) : pas plus de 10 requêtes par seconde, projet gratuit et sans paywall.

Contenu de fan non officiel, autorisé par la [Fan Content Policy](https://company.wizards.com/fancontentpolicy). Non approuvé par Wizards. Des parties des éléments utilisés sont la propriété de Wizards of the Coast. ©Wizards of the Coast LLC.
