# Clameur — Sous-projet 2 : le ciel topographique

**Date :** 2026-09-12
**Statut :** design validé section par section avec le mainteneur, relu deux fois
**Licence du projet :** AGPL-3.0

---

## 1. Intention

Ressortir le ciel, en sommeil depuis le 2026-09-01, sous une forme qui tienne
debout : une **carte topographique** du corpus, où le relief dit la densité des
sujets, où les régions portent des noms tirés des mots-clés, et où l'on peut
partir à la **dérive** d'une clameur à sa voisine.

La référence est WizMap (Polo Club, Georgia Tech), dont on reprend le partage :
le serveur produit une grille de densité, le navigateur en tire les courbes de
niveau et les étiquettes. La référence esthétique est *Topography of a Talk*
(The Visual Agency) : un réseau sémantique lu comme un paysage.

Le relief répond au défaut du nuage de points : **cent clameurs ne font pas une
belle nuit étoilée, mais elles font un beau paysage**, parce qu'une surface
reste continue là où les points sont rares.

## 2. Ce qui existe, et ce qui bouge

| Pièce | Sort |
|---|---|
| Vecteurs `mistral-embed` 1024D, pgvector | inchangés |
| t-SNE numpy initialisé par PCA, signes d'axes fixés | déplacé tel quel dans `capsules/ciel.py` |
| `Capsule.position_x/y`, stockées | inchangées |
| `make constellation` | garde son nom, appelle le module, écrit aussi le `Ciel` |
| WebSocket `/ws/constellation`, swap OOB des transcriptions | inchangé |
| `liste.html` | **devient le double écran** |
| `constellation.html`, vue `constellation`, `PLAFOND_CONSTELLATION` | **supprimés** : un seul gabarit, plus de code dormant |
| `constellation.js` | **réécrit** |
| `_fiche.html` | pastille creuse sans étoile, teinte par durée, `data-*` de couleur, `data-choisir` retiré |
| README (« le ciel, en sommeil »), aide du Makefile | mis à jour |

**Mesure du 2026-09-12**, sur 100 clameurs aux vrais vecteurs : **100 % des
étoiles ont pour plus proche voisine l'une de leurs 5 plus proches par le sens.**
La projection n'est donc pas le maillon à améliorer.

## 3. Décisions arrêtées

| | Décision | Raison |
|---|---|---|
| D1 | `/` redevient le **double écran** : liste et ciel | La vision d'origine, et la liste seule ne montre aucun voisinage |
| D2 | Le calcul passe en **tâche Celery**, déclenchée par les dépôts | C'est ce qui règle la clameur neuve invisible, cause de la mise en sommeil |
| D3 | **Partage WizMap** : serveur pour le sens, navigateur pour le dessin | Le nommage se teste en pytest ; les marching squares ne se réécrivent pas |
| D4 | Les régions sont nommées par les **tags d'auteur d'abord**, machine en repli | La parole de l'auteur prime ; §10 de la spec de la borne |
| D5 | La couleur des étoiles dit la **durée** par défaut, la brillance dit la **fraîcheur** | Aujourd'hui la teinte répète la position : elle n'apprend rien |
| D6 | Un sélecteur **Colorer par** (durée · voix · heure) | Demandé par le mainteneur ; le changement est une simple relecture de la page |
| D7 | La **dérive** de proche en proche, pas le trajet A → B | Un seul geste, praticable au doigt, sans graphe côté serveur |
| D8 | Sur mobile, un **bandeau qui se replie** et cadre l'étoile en cours | Un ciel de 250 px n'a ni cible touchable ni étiquette lisible |
| D9 | **Pas de graphe de forces**, pas de table d'arêtes | Décision de la spec de la borne : les étoiles doivent rester fixes |

**Le compromis assumé (D2 contre la promesse de fixité).** Recalculer à chaque
vague de dépôts déplace toutes les étoiles. La promesse devient : *les étoiles
sont fixes entre deux vagues*. Une page ouverte, elle, ne bouge jamais.

## 4. Le calcul — `capsules/ciel.py`

Un module de **fonctions pures**, appelé à la fois par la commande
`projeter_la_constellation` et par la tâche Celery. On y déplace `_pca`,
`_tsne` et `_fidelite`, aujourd'hui méthodes de la commande. C'est le seul
remaniement du code existant : il évite deux copies de l'algorithme.

### 4.1 La densité

Une KDE gaussienne en numpy sur une grille de **96 × 96 cases** couvrant
[0, 1]², évaluée **au centre de chaque case** — la case `(i, j)` est centrée en
`((i + 0,5)/96, (j + 0,5)/96)`, ce qui correspond exactement à la convention de
d3-contour, qui place la valeur d'indice `i` en `i + 0,5`. La grille est
normalisée de 0 à 1. Pas d'échantillonnage : 96² × 600 points passent en
quelques millisecondes.

**La largeur de bande est une constante : 3,5 cases.** La règle de Silverman ne
mesure rien ici : après la mise à l'échelle par axe, l'écart-type vaut toujours
environ 0,25, et la largeur rétrécirait avec la taille du corpus — le relief
changerait de nature en grandissant.

`grille[y][x]` : **la première dimension est la ligne, donc y**, comme le
`meshgrid` de WizMap. Un relief transposé est une erreur silencieuse.

### 4.2 Les sommets et les régions

1. Un **sommet** est un maximum local strict (voisinage de 8), **cherché sur la
   grille flottante, avant l'arrondi à 3 décimales** : arrondis, les plateaux
   tuent la stricte inégalité. Aucun seuil de hauteur : un sujet minoritaire a
   droit à son nom.
2. Chaque clameur rejoint le **sommet le plus proche**. Pas de montée de pente :
   plateaux, égalités et bords en feraient trois cas particuliers pour rien.
3. Une région de **moins de 3 clameurs** n'est pas nommée. C'est ce seuil, et
   lui seul, qui écarte le bruit.

### 4.3 Le nom d'une région

Score TF-IDF par classe, celui de BERTopic que reprend WizMap :

```
score(clé) = (clameurs de la région portant la clé / taille de la région)
             × log(1 + clés distinctes du ciel / clameurs du ciel portant la clé)
```

- **Une clameur compte une fois par clé**, quelle que soit l'origine et même si
  elle porte deux fois le même mot (l'auteur écrit « quartier », la machine
  aussi : la fiche le déduplique déjà à l'affichage).
- Les clés sont **repliées** : NFKD sans diacritiques, minuscules, sans `s` ni
  `x` final. « voisin » et « voisins » comptent ensemble, sinon le seuil de 2
  n'est jamais atteint. On **affiche la forme la plus fréquente**.
- Le nom retenu est la meilleure clé portée par **au moins 2 clameurs** de la
  région — **et la parole de l'auteur passe d'abord** : on cherche le meilleur
  score parmi les clés portées par au moins 2 clameurs **comme tag d'auteur**,
  et l'on ne se rabat sur les autres que s'il n'en existe aucune. Sans cette
  priorité, huit « boulangerie » proposés par la machine battraient toujours
  deux « pain » écrits à la main, et la région prendrait un mot que personne
  n'a prononcé. L'origine affichée suit : « auteur » dans le premier cas,
  « machine » dans le second. À défaut de clé qualifiée, la région reste sans
  nom.
- Une clé déjà donnée à une région plus grosse n'est pas réutilisée.
- `regions` est **triée par poids décroissant**, ce qui est aussi l'ordre du
  placement glouton des étiquettes.

## 5. Le stockage — le singleton `Ciel`

Un `SingletonModel` django-solo dans l'app **`capsules`** (migration `0007`),
comme `Reglages` dans `bornes` :

| Champ | Contenu |
|---|---|
| `grille` | `JSONField(default=list)` : 96 listes de 96 flottants à 3 décimales (~40 Ko) |
| `regions` | `JSONField(default=list)` : `{x, y, nom, origine, poids}`, `x` et `y` en [0, 1] |
| `calcule_le` | `DateTimeField(null=True)` |

Pas de champ `nombre` : il se déduit d'une requête.

**Un ciel vide**, c'est `grille = []`, `regions = []`, et **toutes les positions
à `None`** — cohérent avec le test qui exige qu'une projection impossible ne
laisse aucune position derrière elle.

Les positions restent sur `Capsule` : deux colonnes mises à jour par
`bulk_update`, qui ne ressuscite jamais une capsule retirée pendant le calcul.

**Une seule transaction**, dans cet ordre : `Ciel.get_solo()` (la ligne doit
exister avant d'être verrouillée), `select_for_update()`, le calcul, puis
l'écriture — `bulk_update` des positions, remise à `None` des positions des
capsules non projetées, `Ciel.save()`. Sans cela, un échec à mi-chemin
afficherait les étoiles d'une projection sur le relief de la précédente.

**Garde-fous** : moins de 3 clameurs projetables, ou une grille non finie, et
l'on écrit un **ciel vide**. Ce garde-fou est la **seule** barrière contre le
NaN : `json_script` sérialise `NaN` tel quel, et `JSON.parse` casse alors en
silence — un ciel entièrement vide, sans un mot dans la console.

**La commande écrit le `Ciel` elle aussi**, sinon `make constellation` laisserait
un relief périmé sur des positions neuves. Son option `--tout` est **retirée** :
projeter les capsules retirées les ferait entrer dans la densité.

## 6. Le déclenchement

- `transcrire` relance `taguer` **et** `embarquer` en parallèle, comme avant la
  mise en sommeil. Chacune ne touche que le message d'erreur qu'elle a écrit.
- **Quatre chemins** appellent `programmer_le_recalcul()` : la réussite de
  `taguer`, celle d'`embarquer`, la vue `retirer_capsule`, et les actions
  d'admin `retirer` et `republier` — qui passent par `queryset.update()` et
  n'émettent donc aucun signal.
- La fonction pose un verrou `cache.add("ciel:programme")` **de la durée du
  délai** et enfile `recalculer_le_ciel` avec un **délai de 120 s**. Une rafale
  de dépôts ne coûte qu'un calcul, et les tags machine ont le temps d'arriver.
- **La tâche efface le verrou dès son premier geste** : une clameur déposée
  pendant le calcul programme bien le suivant, au lieu d'attendre un dépôt de
  plus.
- La tâche prend `select_for_update()` sur le `Ciel` : deux workers
  (`--concurrency=2` en production) ne calculent pas en même temps.
- `programmer_le_recalcul()` **avale et journalise ses erreurs**, comme
  `_enfiler`. Redis mort, le retrait LCEN doit passer quand même.
- `capsules.ciel` est importé **paresseusement** dans la tâche : `tasks.py` est
  importé par `publication.py`, et numpy n'a rien à faire dans un worker web.

**Quand relancer le t-SNE.** La tâche n'a pas d'argument — elle relit toujours
l'état frais, et reste idempotente sous `acks_late`. La règle est donc
auto-descriptive : **le t-SNE tourne si et seulement s'il existe une clameur
publiée dont le vecteur est exploitable et la position absente.** Sinon, seules
la densité et les régions sont recalculées, en quelques millisecondes — un
retrait n'a aucune raison de relancer une projection.

Pour que cette règle termine, **un vecteur inexploitable (norme nulle ou non
fini) est noté dans `erreur_enrichissement`** et n'est plus candidat : sans
cela, une capsule abîmée relancerait le t-SNE à chaque calcul, à vie.

**Invariant I2 préservé** : la publication ne dépend jamais de Celery. Le ciel
prend du retard, il ne bloque rien.

**Coût** : 0,6 s pour 100 clameurs, 23 s pour 600, dans un slot de worker sur
deux. Un ticket peut donc attendre jusqu'à 23 s : c'est accepté, et écrit ici.

## 7. La page

### 7.1 Structure et données

`/` rend le double écran. La requête de la liste est celle d'aujourd'hui :
toutes les clameurs publiées, la recherche `?q=`, le plafond de la liste.

**Les étoiles ne se lisent pas dans le DOM.** Le JavaScript dormant construisait
le ciel en parcourant les fiches ; or HTMX remplace `#resultats` à chaque frappe,
et `/?q=boulangerie` partagé ne rend qu'une poignée de fiches — le ciel serait
amputé. Trois `json_script` portent donc :

1. `grille` — 96 × 96 flottants ;
2. `regions` — la liste triée par poids ;
3. `etoiles` — **toutes** les clameurs publiées qui ont une position,
   indépendamment de `q` : `uuid`, `x`, `y`, `ecoutes`, `duree`, `voix`,
   `heure`, `titre`, `audio`, `type_mime`.

`json_script` échappe et ne localise pas : pas de virgule décimale, contrairement
aux attributs `data-*` qui exigent `localize off`.

**La recherche.** Après chaque `htmx:afterSwap`, le JavaScript relit les `uuid`
présents dans `#resultats` : les étoiles absentes du résultat **pâlissent**
(opacité 0,35, jamais moins — une étoile de 2 px à 0,1 disparaît). Le relief et
les noms de région **ne bougent pas** : ils décrivent le corpus, pas le
résultat. Une recherche sans résultat laisse donc un paysage entier et des
étoiles toutes pâles.

**Disposition.**
- **Bureau (> 800 px)** : la liste à gauche (en-tête, recherche, fiches), le
  ciel à droite.
- **Mobile (≤ 800 px)** : la page défile, le ciel est collé en haut. Il a
  **deux états** : déployé (50 % de la hauteur) et replié (22 %). On passe à
  l'état replié dès que la page a défilé de 260 px, et l'on revient en haut au
  double-toucher. Deux états valent mieux qu'une hauteur continue pilotée au
  défilement : c'est plus simple, et c'est déjà ce que le mode
  `prefers-reduced-motion` imposait.
- **Replié, le bandeau cadre une fenêtre de 420 unités autour de l'étoile
  choisie**, au lieu de montrer un ciel illisible.

**La liste montre toutes les clameurs publiées, même sans vecteur.** Une fiche
sans étoile porte une **pastille creuse**. C'est ce qui répare le défaut qui
avait fait mettre le ciel en sommeil.

`decrire_une_clameur` expose `a_une_etoile` ; le `position_x or 0.5` actuel
empilerait toutes les clameurs neuves au centre du ciel.

Le `data-choisir` de la fiche disparaît : le nom est un lien vers `/c/<uuid>`,
et le faire à la fois sélectionner et naviguer quitterait la page.

Sans JavaScript, la liste fonctionne entièrement ; le ciel reste vide.

### 7.2 Le rendu du ciel

**Bibliothèques** : `d3-array` 3.2.4 (17 Ko) et `d3-contour` 4.0.2 (5,7 Ko),
figés dans `static/capsules/vendor/` comme htmx, **`d3-array` chargé en premier**
(les paquets UMD s'attendent dans cet ordre). Les anneaux GeoJSON sont convertis
en chemins par une fonction de cinq lignes, avec **`fill-rule: evenodd`** pour
que les anneaux intérieurs restent des trous : `d3-geo` ne vaut pas ses 50 Ko
pour cela.

- **Le relief** : `size([96, 96])` sur la grille aplatie, **10 seuils à `n/11`,
  tous dessinés** — le `slice(1)` de WizMap n'a pas d'objet ici, puisqu'aucun
  seuil ne vaut zéro. Les coordonnées rendues sont en cases : on les multiplie
  par `1000/96`, **sans retourner l'axe y**, puisque la grille et le ciel ont la
  même orientation. Les remplissages restent dans les tons du papier (clarté
  0,205 → 0,31, chroma 0,028, teinte 45), avec un filet d'encre à 10 %.
- **Les étiquettes** : au sommet, en `--font-display`, trois tailles selon le
  poids, **avec un halo de papier — obligatoire, pas décoratif** : c'est lui qui
  tient le contraste d'un tag machine en encre ténue posé sur les courbes. Tag
  machine : italique, encre ténue, mention « proposé par la machine » pour les
  lecteurs d'écran. Placement glouton dans l'ordre des poids : une étiquette qui
  chevauche une étiquette déjà posée, **marge comprise**, est retirée, jamais
  déplacée au hasard. La taille visée est 14 px à l'écran : elle est donc
  recalculée à chaque redimensionnement et à chaque changement d'état du
  bandeau, **ce qui rejoue tout le placement**.
- **Les étoiles** : rayon inchangé (racine carrée des écoutes, plafonné).
  Teinte selon l'encodage choisi, clarté de 0,60 à 0,86 selon le rang de
  fraîcheur, chroma 0,13.

| Encodage | Teintes |
|---|---|
| **Durée** (défaut) | arc chaud 350° → 100°, de la brève à la longue (bornée à 180 s) |
| Voix | 78° une voix · 38° deux voix · 12° trois et plus |
| Heure | 80° le jour · 5° la nuit |

Le choix tient dans `localStorage`. Le serveur rend la teinte **durée** pour que
la page soit juste avant l'arrivée du JavaScript. Les pastilles des fiches
suivent la même couleur.

- **Le toucher** : un appui n'importe où choisit l'étoile la plus proche dans un
  rayon de 30 px à l'écran ; au-delà, rien. Sans cela, une étoile de 2 px n'est
  atteignable par aucun doigt. Les étoiles restent focusables au clavier.
- **Toucher une étiquette** remplit la recherche avec ce tag, ce qui déclenche
  la recherche HTMX existante.
- `prefers-reduced-motion` coupe les animations, **y compris le tracé de la
  dérive**.

## 8. La dérive

Un bouton « Laisser dériver ». La dérive part de la clameur en cours, ou de la
première de la liste. À la fin de chaque écoute, **la plus proche voisine pas
encore entendue** démarre, et un trait ambre s'allonge d'étoile en étoile.

**Elle ne choisit que parmi les clameurs présentes dans la liste**, donc dans le
résultat de recherche courant : c'est là que vivent le lecteur, l'URL de l'audio
et la cible du défilement. Plus de candidate, la dérive s'arrête et le bouton
reprend son nom. Une recherche filtrée devient ainsi une dérive thématique.

**Un seul élément audio, débloqué par l'appui initial, dont on change la
source.** Sur iOS, appeler `play()` sur un autre lecteur que celui qu'un doigt a
touché est refusé : c'est la contrainte qui dicte la conception. Les lecteurs
des fiches restent en place pour l'écoute à la main.

À chaque étape : la fiche est sélectionnée, la liste défile (bureau) ou le
bandeau cadre l'étoile (mobile), l'écoute est comptée par le POST existant, et
le titre est annoncé en `aria-live`.

La dérive s'arrête au bouton, au toucher d'une autre étoile, ou au lancement
d'un lecteur de fiche. Jamais de son qui continue tout seul. Les clameurs
entendues vivent **dans la page**, jamais dans un cookie.

**Effet de bord assumé** : une dérive de trente clameurs compte trente écoutes,
donc grossit trente étoiles. Le compteur mesurera deux gestes différents.

## 9. Tests et vérification

**`capsules/ciel.py`** :
- densité finie et bornée, même à positions identiques ;
- **sommets sur des positions construites** — trois amas nets donnent trois
  sommets. C'est la seule forme de test qui prouve quelque chose : le nombre de
  sommets qu'un t-SNE produit sur douze points n'est garanti par rien ;
- sur le **corpus du régime réel**, un encadrement : au moins un sommet par
  groupe, au plus le double ;
- nommage : auteur d'abord, repli machine, seuil de 2 clameurs, dédoublonnage
  entre régions, pluriels et accents repliés, une clameur comptée une fois ;
- moins de 3 clameurs ⇒ ciel vide écrit, **toutes positions à `None`**.

**La tâche** : verrou effacé au départ ; deux appels concurrents sérialisés ;
positions et `Ciel` dans une transaction ; le t-SNE ne tourne pas quand rien
n'attend de position ; un vecteur inexploitable ne le relance pas indéfiniment ;
l'action d'admin `retirer` programme bien un recalcul ; **Redis mort, le retrait
LCEN passe quand même**.

**La vue** : `/` rend le double écran ; la recherche filtre la liste sans
toucher au relief ; une clameur sans vecteur figure dans la liste sans étoile ;
les positions sortent sans virgule décimale (le test existant, qui avait déjà
attrapé un ciel entièrement NaN) ; la page se charge avec un `Ciel` vide.

**Tests existants à retourner** : `test_l_embedding_ne_part_plus_derriere_la_transcription`,
les teintes tirées de la position, et les appels aux méthodes de la commande
déplacées dans le module.

**Les fixtures gagnent de vrais tags machine** sur une partie du corpus : sans
eux, le repli en italique n'est exercé ni par les tests ni à l'œil.

**Le JavaScript se vérifie en vrai**, dans un navigateur, bureau et téléphone, y
compris l'enchaînement de la dérive sur iOS. La suite de tests reste hors ligne.

## 10. Hors périmètre

- **Le rattrapage des vecteurs manquants en production** (les clameurs publiées
  depuis le 02/09 n'en ont pas). Ce sera une option de la commande. Noter que
  `embarquer` exige une transcription.
- **La notification « le ciel a bougé »** sur une page déjà ouverte.
- Le trajet A → B façon *X Degrees of Separation*.
- Le zoom et le déplacement dans le ciel : les régions et le bandeau suffisent
  à cette échelle.

**Au déploiement**, `make constellation` fait partie de la manœuvre : rien ne
déclenche de calcul tant qu'aucune clameur n'est déposée, et la production n'a
plus de vecteurs frais depuis le 02/09.

## 11. Ce que la maquette a montré

Une maquette jetable, nourrie par les 100 clameurs du corpus réel, a servi à
juger avant d'écrire le code définitif :

- le relief donne **huit massifs nets**, et les noms tombent sur les sommets ;
- les étiquettes demandaient une **marge de collision** : deux sommets voisins
  d'un même massif donnaient deux noms collés ;
- les tailles de texte devaient être relevées ;
- les trois familles de couleur se distinguent sur le papier brun.

Elle a aussi montré une limite du corpus : **les fixtures ne produisent aucun
tag machine**, donc le repli n'y est pas visible. D'où le §9.
