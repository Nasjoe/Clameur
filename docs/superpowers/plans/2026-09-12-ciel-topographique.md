# Plan d'implémentation — le ciel topographique

> **Pour les agents :** SOUS-SKILL REQUIS — `superpowers:subagent-driven-development` (recommandé) ou `superpowers:executing-plans`, tâche par tâche. Les étapes sont cochables (`- [ ]`).

**But :** ressortir le ciel des clameurs en carte topographique — relief de densité, régions nommées par les tags, couleurs qui portent une information, dérive sonore de proche en proche — sur `/` en double écran, recalculé tout seul par Celery.

**Architecture :** le partage de WizMap. Le serveur calcule ce qui relève du sens (positions t-SNE, grille de densité 96×96, régions nommées) dans un module de fonctions pures, et le stocke dans un singleton `Ciel`. Le navigateur ne fait que dessiner : `d3-contour` trace les courbes sur cette même grille, place les étiquettes, colore les étoiles et gère la dérive.

**Pile :** Django 5, Celery, pgvector, numpy, htmx 2, d3-array 3.2.4 + d3-contour 4.0.2 (UMD, dans `vendor/`), pytest.

**Spec :** `docs/superpowers/specs/2026-09-12-ciel-topographique-design.md` — à lire avec ce plan.

**État au 2026-09-12 :** tâches 1 à 12 exécutées dans le working tree, **227 tests verts, ruff propre, aucune commande git passée**. Les tâches 8 à 11 ont été écrites d'un bloc dans `capsules/static/capsules/ciel.js` : elles touchent le même fichier et ne se vérifient qu'à l'œil, pas séparément.

**Ajouté hors plan, à la demande du mainteneur :** le §10 « hors périmètre » annonçait le rattrapage des vecteurs manquants comme restant à écrire. Il est fait — non pas dans une nouvelle cible, mais comme option `--rattraper` de `projeter_la_constellation`, et `make constellation` marche désormais **en dev et en prod** (`ARGS=--rattraper`). Trois tests, et un aller-retour éprouvé en vrai sur une clameur dont le vecteur avait été effacé.

Reste à faire par le mainteneur : la vérification sur un vrai téléphone (bandeau, dérive sur iOS), puis les commits.

## Contraintes globales

- **AUCUNE COMMANDE `git`, JAMAIS, SANS L'ACCORD EXPLICITE DU MAINTENEUR.** Cela inclut `checkout --`, `stash`, `reset --hard`, `restore --`, `clean -f`, autant que `add`, `commit`, `push`. Les étapes « Commit » de ce plan sont des **propositions** : on affiche le message, on demande, on attend. **Jamais de mention `Co-Authored-By`.**
- **Pas de `ruff format` ni de `ruff check --fix` sur un fichier existant.** Sur un fichier neuf uniquement.
- **Tout passe par Docker.** `make test` lance la suite, `make start` la pile, `make constellation` la projection. Le worker Celery **ne recharge pas le code** : après toute modification de `capsules/tasks.py` ou `capsules/ciel.py`, `docker compose restart celery`.
- **La suite de tests reste hors ligne.** Aucun appel réseau : le conteneur porte une vraie clé Mistral.
- **Commentaires en français**, expliquant le POURQUOI des choix contre-intuitifs, 1 à 3 lignes. On explique le code, on ne raconte pas la session : pas de date, pas de récit.
- **Constantes figées par la spec :** grille `CASES = 96`, noyau `LARGEUR_NOYAU = 3.5` cases, `NIVEAUX = 10` seuils à `n/11`, `MIN_PAR_REGION = 3` clameurs, `MIN_PAR_TAG = 2` clameurs, délai de recalcul `120` s, rayon de toucher `30` px, opacité plancher des étoiles pâlies `0.35`, clarté des étoiles de `0.60` à `0.86`, chroma `0.13`.
- **`grille[y][x]`** : première dimension = ligne = y. Un relief transposé est une erreur silencieuse.
- **Invariant I2 :** la publication ne dépend jamais de Celery. Rien de ce qui suit ne doit pouvoir faire échouer une publication ou un retrait.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `capsules/ciel.py` (créé) | Fonctions pures : projection, densité, sommets, régions, nommage. Aucun accès base. |
| `capsules/models.py` (modifié) | Ajout du singleton `Ciel`. |
| `capsules/migrations/000X_ciel.py` (généré) | La table du singleton. |
| `capsules/tasks.py` (modifié) | `programmer_le_recalcul()`, tâche `recalculer_le_ciel`, remise en file d'`embarquer`. |
| `capsules/views.py` (modifié) | Contexte du double écran, `a_une_etoile`, teinte par durée ; suppression de la vue dormante. |
| `capsules/admin.py` (modifié) | Les actions `retirer` et `republier` programment un recalcul. |
| `capsules/management/commands/projeter_la_constellation.py` (réécrit) | Enveloppe mince autour du module ; écrit aussi le `Ciel`. |
| `capsules/templates/capsules/liste.html` (modifié) | Devient le double écran. |
| `capsules/templates/capsules/_fiche.html` (modifié) | Pastille creuse, données de couleur, `data-choisir` retiré. |
| `capsules/static/capsules/ciel.js` (créé) | Tout le ciel : relief, étiquettes, étoiles, toucher, bandeau, dérive. |
| `capsules/static/capsules/constellation.js`, `templates/capsules/constellation.html` | **Supprimés.** |
| `capsules/static/capsules/vendor/d3-array-3.2.4.min.js`, `d3-contour-4.0.2.min.js` | Bibliothèques figées. |
| `tests/test_ciel.py` (créé) | Les fonctions pures. |
| `tests/test_recalcul.py` (créé) | La tâche, le verrou, les déclencheurs. |
| `tests/test_constellation.py` (modifié) | Réoriente les tests existants vers le module. |
| `tests/test_enrichissement.py` (modifié) | Retourne le test du sommeil. |

---

## Tâche 1 : le module `capsules/ciel.py` — projection et densité

**Fichiers :**
- Créer : `capsules/ciel.py`
- Créer : `tests/test_ciel.py`
- Lire (source du déménagement) : `capsules/management/commands/projeter_la_constellation.py:152-283`

**Interfaces :**
- Produit — **tous ces noms sont publics, sans souligné** : ils sont appelés depuis la commande, la tâche et les tests. `projeter(vecteurs: np.ndarray) -> np.ndarray` (n×2, valeurs dans [MARGE, 1-MARGE]) ; `pca(vecteurs) -> np.ndarray` (n×2) ; `tsne(vecteurs, depart) -> np.ndarray` (n×2) ; `densite(positions: np.ndarray) -> np.ndarray` (96×96, normalisée 0→1, `grille[y][x]`) ; `fidelite(vecteurs, positions) -> float` ; `combien_de_proches(nombre: int) -> int` ; les constantes `CASES`, `LARGEUR_NOYAU`, `MARGE`, `VOISINES`, `ITERATIONS`.

- [ ] **Étape 1 : écrire les tests de la densité**

```python
"""Les fonctions pures du ciel. / The sky's pure functions."""

import numpy as np

from capsules import ciel


def test_la_densite_a_la_forme_et_l_orientation_attendues():
    """`grille[y][x]` : la première dimension est la ligne, donc y.

    Une grille transposée ne lève aucune erreur : elle rend simplement un
    relief en miroir de ses étoiles, et personne ne le voit avant l'écran.
    """
    positions = np.array([[0.2, 0.8]])   # à gauche, en bas
    grille = ciel.densite(positions)

    assert grille.shape == (ciel.CASES, ciel.CASES)
    ligne, colonne = np.unravel_index(grille.argmax(), grille.shape)
    assert abs(colonne / ciel.CASES - 0.2) < 0.05
    assert abs(ligne / ciel.CASES - 0.8) < 0.05


def test_la_densite_est_normalisee_et_finie():
    alea = np.random.default_rng(3)
    grille = ciel.densite(alea.random((40, 2)))

    assert np.isfinite(grille).all()
    assert grille.min() >= 0
    assert abs(grille.max() - 1.0) < 1e-9


def test_des_positions_identiques_ne_produisent_pas_de_nan():
    """Le cas dégénéré : cent clameurs au même endroit. Une largeur de bande
    calculée sur l'écart-type vaudrait zéro, et toute la grille serait NaN."""
    grille = ciel.densite(np.full((100, 2), 0.5))

    assert np.isfinite(grille).all()
    assert grille.max() > 0
```

- [ ] **Étape 2 : lancer les tests et vérifier qu'ils échouent**

Run : `make test PYTEST_ARGS="tests/test_ciel.py -v"` (ou `docker compose run --rm web pytest tests/test_ciel.py -v`)
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'capsules.ciel'`.

- [ ] **Étape 3 : créer le module avec la projection déménagée et la densité**

Créer `capsules/ciel.py`. Les fonctions `projeter`, `pca`, `tsne`, `fidelite`, `combien_de_proches` sont **reprises telles quelles** depuis `projeter_la_constellation.py` (méthodes `_projeter`, `_pca`, `_tsne`, `_fidelite`, `_combien_de_proches`), sans changer une ligne d'algorithme : elles deviennent des fonctions de module, **perdent leur souligné** puisqu'elles sont désormais appelées du dehors, et leurs docstrings et commentaires les suivent intégralement. S'y ajoute :

```python
CASES = 96

# EN CASES, ET NON PAR LA REGLE DE SILVERMAN. Apres la mise a l'echelle par
# axe, l'ecart-type des positions vaut toujours environ un quart : Silverman ne
# mesurerait plus rien, et sa largeur retrecirait avec la taille du corpus — le
# relief changerait de nature en grandissant.
# / A constant in cells: after per-axis rescaling, Silverman measures nothing.
LARGEUR_NOYAU = 3.5


def densite(positions: np.ndarray) -> np.ndarray:
    """La densite des clameurs sur une grille CASES x CASES, ramenee a [0, 1].

    `grille[y][x]` : la premiere dimension est la ligne. C'est la convention du
    `meshgrid` de WizMap et celle qu'attend `d3.contours`, qui place la valeur
    d'indice i au centre de la case, en i + 0,5.
    / grille[y][x]: rows first, matching d3.contours' cell-centre convention.
    """
    grille = np.zeros((CASES, CASES))
    portee = int(np.ceil(3 * LARGEUR_NOYAU))

    for x, y in positions:
        # On ne somme le noyau que sur les cases voisines : au-dela de trois
        # largeurs, la gaussienne ne pese plus rien et couterait CASES au carre
        # par clameur. / Beyond three widths the gaussian adds nothing.
        cx, cy = x * CASES - 0.5, y * CASES - 0.5
        i0, i1 = max(0, int(cx - portee)), min(CASES - 1, int(np.ceil(cx + portee)))
        j0, j1 = max(0, int(cy - portee)), min(CASES - 1, int(np.ceil(cy + portee)))
        if i1 < i0 or j1 < j0:
            continue
        colonnes = np.arange(i0, i1 + 1)
        lignes = np.arange(j0, j1 + 1)
        ecarts = ((lignes[:, None] - cy) ** 2 + (colonnes[None, :] - cx) ** 2)
        grille[j0:j1 + 1, i0:i1 + 1] += np.exp(-ecarts / (2 * LARGEUR_NOYAU**2))

    maximum = grille.max()
    return grille / maximum if maximum > 0 else grille
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Run : `docker compose run --rm web pytest tests/test_ciel.py -v`
Attendu : 3 tests PASSÉS.

- [ ] **Étape 5 : proposer le commit**

Message proposé — **ne pas exécuter sans accord** :
```
feat(ciel): module des fonctions pures, projection et densité
```

---

## Tâche 2 : les sommets, les régions et leurs noms

**Fichiers :**
- Modifier : `capsules/ciel.py`
- Modifier : `tests/test_ciel.py`

**Interfaces :**
- Consomme : `densite`, `CASES` (tâche 1).
- Produit : `clef_de_tag(nom: str) -> str` ; `sommets(grille: np.ndarray) -> list[tuple[float, float]]` (x, y dans [0, 1]) ; `regions(grille, positions, tags) -> list[dict]` où `tags` est une liste alignée sur `positions`, chaque élément étant une liste de `(nom, origine)`, et chaque dict rendu vaut `{"x", "y", "nom", "origine", "poids"}`, trié par `poids` décroissant.

- [ ] **Étape 1 : écrire les tests des sommets et du nommage**

```python
def _trois_amas():
    """Trois amas nets, construits à la main.

    On ne demande pas ce nombre à un t-SNE : sur douze points, rien ne garantit
    le nombre de sommets qu'il produit, et le test mesurerait la projection au
    lieu de mesurer la détection.
    """
    alea = np.random.default_rng(5)
    centres = [(0.2, 0.2), (0.8, 0.25), (0.5, 0.8)]
    positions, appartenance = [], []
    for numero, (cx, cy) in enumerate(centres):
        for _ in range(8):
            positions.append((cx + alea.normal(0, 0.02), cy + alea.normal(0, 0.02)))
            appartenance.append(numero)
    return np.asarray(positions), appartenance


def test_trois_amas_donnent_trois_sommets():
    positions, _ = _trois_amas()
    assert len(ciel.sommets(ciel.densite(positions))) == 3


def test_une_region_prend_le_tag_d_auteur_le_plus_caracteristique():
    positions, appartenance = _trois_amas()
    mots = ["boulangerie", "nuit", "exil"]
    tags = [[(mots[numero], "auteur")] for numero in appartenance]

    noms = {region["nom"] for region in ciel.regions(ciel.densite(positions), positions, tags)}
    assert noms == set(mots)


def test_le_tag_machine_ne_sert_que_faute_de_tag_d_auteur():
    positions, appartenance = _trois_amas()
    tags = []
    for numero in appartenance:
        if numero == 0:
            tags.append([("boulangerie", "machine")])
        else:
            tags.append([("nuit" if numero == 1 else "exil", "auteur")])

    par_nom = {r["nom"]: r for r in ciel.regions(ciel.densite(positions), positions, tags)}
    assert par_nom["boulangerie"]["origine"] == "machine"
    assert par_nom["nuit"]["origine"] == "auteur"


def test_le_mot_de_l_auteur_l_emporte_sur_celui_de_la_machine():
    """Huit « boulangerie » proposés par la machine contre deux « pain » écrits
    à la main : au seul score, la machine gagne toujours, et la région prend un
    mot que personne n'a prononcé."""
    positions, appartenance = _trois_amas()
    tags = []
    for numero in appartenance:
        if numero == 0:
            tags.append([("boulangerie", "machine")])
        else:
            tags.append([("nuit" if numero == 1 else "exil", "auteur")])
    for indice in (0, 1):          # deux clameurs de l'amas 0 disent « pain »
        tags[indice] = [("boulangerie", "machine"), ("pain", "auteur")]

    par_poids = sorted(
        ciel.regions(ciel.densite(positions), positions, tags),
        key=lambda region: region["poids"], reverse=True,
    )
    amas = next(r for r in par_poids if r["nom"] in {"pain", "boulangerie"})
    assert amas["nom"] == "pain" and amas["origine"] == "auteur"


def test_singulier_et_pluriel_comptent_ensemble():
    """« voisin » et « voisins » séparés, aucun des deux n'atteint le seuil de
    deux clameurs, et la région reste anonyme."""
    positions, appartenance = _trois_amas()
    tags = []
    for indice, numero in enumerate(appartenance):
        if numero == 0:
            tags.append([("voisins" if indice % 2 else "voisin", "auteur")])
        else:
            tags.append([("nuit" if numero == 1 else "exil", "auteur")])

    noms = {r["nom"] for r in ciel.regions(ciel.densite(positions), positions, tags)}
    assert noms & {"voisin", "voisins"}, "le pluriel a fait rater le seuil"


def test_un_tag_ne_nomme_pas_deux_regions():
    positions, appartenance = _trois_amas()
    tags = [[("quartier", "auteur")] for _ in appartenance]

    regions = ciel.regions(ciel.densite(positions), positions, tags)
    assert [r["nom"] for r in regions].count("quartier") == 1


def test_une_region_de_moins_de_trois_clameurs_n_est_pas_nommee():
    """« nuit » est porté par deux clameurs, donc qualifié comme tag — mais sa
    région n'en compte que deux, et deux clameurs ne font pas une région.

    C'est bien le seuil de région qu'on teste : un tag porté une seule fois
    serait déjà écarté par le seuil de tag, et le test ne prouverait rien.
    """
    positions = np.array([[0.2, 0.2], [0.205, 0.205], [0.8, 0.8]])
    tags = [[("nuit", "auteur")], [("nuit", "auteur")], [("exil", "auteur")]]

    noms = {r["nom"] for r in ciel.regions(ciel.densite(positions), positions, tags)}
    assert "nuit" not in noms
```

- [ ] **Étape 2 : lancer les tests et vérifier qu'ils échouent**

Run : `docker compose run --rm web pytest tests/test_ciel.py -v`
Attendu : ÉCHEC — `AttributeError: module 'capsules.ciel' has no attribute 'sommets'`.

- [ ] **Étape 3 : implémenter sommets, clef_de_tag et regions**

```python
import unicodedata

MIN_PAR_REGION = 3
MIN_PAR_TAG = 2


def clef_de_tag(nom: str) -> str:
    """La forme sous laquelle deux tags comptent pour le meme mot.

    « voisin » et « voisins » separes, aucun des deux n'atteint le seuil de
    deux clameurs et la region reste anonyme. On replie donc les accents et le
    pluriel POUR COMPTER ; l'affichage, lui, garde la forme la plus frequente.
    / Folded for counting only: the displayed form stays the commonest one.
    """
    sans_accents = "".join(
        lettre for lettre in unicodedata.normalize("NFKD", nom)
        if not unicodedata.combining(lettre)
    )
    replie = sans_accents.lower()
    # UNE SEULE finale retiree, jamais toutes : `rstrip("sx")` ramenerait
    # « boss » a « bo » et rapprocherait des mots sans rapport. Et pas sur un
    # mot de trois lettres, ou il ne resterait rien a comparer.
    # / A single trailing letter: rstrip would turn "boss" into "bo".
    return replie[:-1] if len(replie) > 3 and replie[-1] in "sx" else replie


def sommets(grille: np.ndarray) -> list[tuple[float, float]]:
    """Les maximums locaux de la grille, en coordonnees [0, 1].

    CHERCHES SUR LA GRILLE FLOTTANTE, avant tout arrondi : arrondies a trois
    decimales, deux cases voisines deviennent egales, et l'inegalite stricte ne
    trouve plus rien au sommet d'un plateau.
    Aucun seuil de hauteur : un sujet minoritaire a droit a son nom, et c'est
    le seuil de trois clameurs qui ecarte le bruit.
    / Found before rounding, and with no height threshold.
    """
    trouves = []
    for ligne in range(1, CASES - 1):
        for colonne in range(1, CASES - 1):
            valeur = grille[ligne, colonne]
            if valeur <= 0:
                continue
            voisinage = grille[ligne - 1:ligne + 2, colonne - 1:colonne + 2]
            if valeur >= voisinage.max() and (voisinage == valeur).sum() == 1:
                trouves.append(((colonne + 0.5) / CASES, (ligne + 0.5) / CASES))
    return trouves


def regions(grille, positions, tags) -> list[dict]:
    """Les regions nommees du ciel, de la plus grosse a la plus petite.

    `tags` est aligne sur `positions` : pour chaque clameur, ses couples
    (nom, origine). / tags is aligned with positions.
    """
    pics = sommets(grille)
    if not pics:
        return []

    # Chaque clameur rejoint le sommet le plus proche. Pas de montee de pente :
    # plateaux, egalites et bords en feraient trois cas particuliers, pour le
    # meme resultat. / Nearest peak, not gradient ascent.
    pics_array = np.asarray(pics)
    ecarts = ((positions[:, None, :] - pics_array[None, :, :]) ** 2).sum(-1)
    appartenance = ecarts.argmin(axis=1)

    # Combien de clameurs portent chaque cle dans TOUT le ciel : c'est la
    # rarete du TF-IDF. Une clameur compte une fois par cle, meme si l'auteur
    # et la machine ont ecrit le meme mot.
    # / How many clameurs carry each key: the IDF term.
    partout: dict[str, int] = {}
    for mots in tags:
        for cle in {clef_de_tag(nom) for nom, _origine in mots}:
            partout[cle] = partout.get(cle, 0) + 1

    retenues, deja_prises = [], set()
    groupes = sorted(
        ((numero, np.flatnonzero(appartenance == numero)) for numero in range(len(pics))),
        key=lambda couple: len(couple[1]), reverse=True,
    )
    for numero, membres in groupes:
        if len(membres) < MIN_PAR_REGION:
            continue
        nomme = _nommer([tags[indice] for indice in membres], partout, deja_prises)
        if nomme is None:
            continue
        deja_prises.add(nomme["cle"])
        retenues.append({
            "x": round(pics[numero][0], 4), "y": round(pics[numero][1], 4),
            "nom": nomme["nom"], "origine": nomme["origine"], "poids": len(membres),
        })
    return retenues


def _nommer(tags_des_membres, partout, deja_prises) -> dict | None:
    """Le meilleur mot de la region : frequence ici, rarete ailleurs.

    C'est le TF-IDF par classe de BERTopic, que reprend WizMap. Le tag
    d'auteur l'emporte : sa parole prime sur l'hypothese de la machine, et
    l'origine voyage avec le nom pour que le rendu les distingue.
    / Class-based TF-IDF; the author's word wins, and its origin travels with it.
    """
    comptes: dict[str, dict] = {}
    for mots in tags_des_membres:
        # UNE CLAMEUR COMPTE UNE FOIS PAR CLE. L'auteur ecrit « quartier », la
        # machine trouve « quartier » : deux liens en base, une seule voix.
        # / One clameur, one vote per key, whatever its origins.
        vues, vues_de_l_auteur = set(), set()
        for nom, origine in mots:
            cle = clef_de_tag(nom)
            entree = comptes.setdefault(cle, {"n": 0, "auteur": 0, "formes": {}})
            entree["formes"][nom] = entree["formes"].get(nom, 0) + 1
            if cle not in vues:
                entree["n"] += 1
                vues.add(cle)
            if origine == "auteur" and cle not in vues_de_l_auteur:
                entree["auteur"] += 1
                vues_de_l_auteur.add(cle)

    def _meilleure(candidates) -> dict | None:
        meilleur = None
        for cle, entree in candidates:
            score = (entree["n"] / len(tags_des_membres)) * np.log(
                1 + len(partout) / partout.get(cle, 1)
            )
            if meilleur is None or score > meilleur["score"]:
                forme = max(entree["formes"].items(), key=lambda couple: couple[1])[0]
                meilleur = {
                    "score": score, "nom": forme, "cle": cle,
                    "origine": "auteur" if entree["auteur"] >= MIN_PAR_TAG else "machine",
                }
        return meilleur

    qualifiees = [
        (cle, entree) for cle, entree in comptes.items()
        if entree["n"] >= MIN_PAR_TAG and cle not in deja_prises
    ]
    # LA PAROLE DE L'AUTEUR PASSE D'ABORD, ET PAS SEULEMENT A EGALITE DE SCORE.
    # Huit clameurs etiquetees « boulangerie » par la machine contre deux
    # « pain » ecrits a la main : au score, la machine gagne toujours, et la
    # region prend un mot que personne n'a prononce. On cherche donc le
    # meilleur parmi les cles portees par au moins deux AUTEURS, et l'on ne se
    # rabat sur les autres que s'il n'y en a aucune.
    # / The author's own word wins outright, not merely on a tie.
    par_auteur = [
        (cle, entree) for cle, entree in qualifiees if entree["auteur"] >= MIN_PAR_TAG
    ]
    return _meilleure(par_auteur) or _meilleure(qualifiees)
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Run : `docker compose run --rm web pytest tests/test_ciel.py -v`
Attendu : 9 tests PASSÉS.

- [ ] **Étape 5 : ajouter l'encadrement sur le corpus du régime réel**

**Ne pas borner les sommets bruts.** Mesuré : sur `_corpus_du_regime_reel` (six groupes de huit), le t-SNE éclate chaque groupe en sous-taches et la détection trouve 12 à 31 sommets selon la graine. C'est normal — un sommet n'est pas un thème — et un encadrement sur ce nombre rendrait le test instable sans rien prouver.

Ce qui se teste, c'est le **résultat visible** : les régions nommées.

```python
@pytest.mark.django_db
def test_sur_un_corpus_realiste_les_regions_restent_peu_nombreuses_et_distinctes(reglages):
    """Six groupes de huit ne doivent pas produire trente noms sur la carte.

    Le nombre de SOMMETS, lui, n'est pas testable : le t-SNE éclate chaque
    groupe en sous-tâches, et il en trouve de douze à trente selon la graine.
    Ce qui compte est ce qu'on lit à l'écran.
    """
    from tests.test_constellation import _corpus_du_regime_reel

    capsules, groupe_de = _corpus_du_regime_reel(reglages)
    vecteurs = np.vstack([np.asarray(c.embedding, dtype=float) for c in capsules])
    positions = ciel.projeter(vecteurs)
    tags = [[(f"groupe-{groupe_de[c.uuid]}", "auteur")] for c in capsules]

    regions = ciel.regions(ciel.densite(positions), positions, tags)

    assert 1 <= len(regions) <= 6, f"{len(regions)} régions pour six groupes"
    noms = [region["nom"] for region in regions]
    assert len(noms) == len(set(noms)), "un même mot nomme deux régions"
```

- [ ] **Étape 6 : proposer le commit**

```
feat(ciel): sommets, régions et nommage par les tags
```

---

## Tâche 3 : le singleton `Ciel`

**Fichiers :**
- Modifier : `capsules/models.py`
- Générer : `capsules/migrations/000X_ciel.py`
- Modifier : `tests/test_ciel.py`

**Interfaces :**
- Produit : `capsules.models.Ciel` avec `grille` (JSON), `regions` (JSON), `calcule_le` (date nullable), et `Ciel.get_solo()`.

- [ ] **Étape 1 : écrire le test du ciel vide**

```python
import pytest

from capsules.models import Ciel


@pytest.mark.django_db
def test_un_ciel_neuf_est_vide_et_ne_fait_pas_tomber_la_page(client, reglages):
    """Avant le premier calcul, le singleton existe et ne porte rien."""
    objet = Ciel.get_solo()

    assert objet.grille == []
    assert objet.regions == []
    assert objet.calcule_le is None
    assert client.get("/").status_code == 200
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Run : `docker compose run --rm web pytest tests/test_ciel.py -k ciel_neuf -v`
Attendu : ÉCHEC — `ImportError: cannot import name 'Ciel'`.

- [ ] **Étape 3 : ajouter le modèle**

Dans `capsules/models.py`, importer `from solo.models import SingletonModel` (comme `bornes/models.py`) et ajouter :

```python
class Ciel(SingletonModel):
    """Le relief du corpus, calcule d'un bloc et servi tel quel.

    UNE SEULE LIGNE, comme les reglages : le ciel est global par nature. Une
    projection se recalcule pour tout le monde ou pour personne.
    / One row: a projection is global by nature.
    """

    # `grille[y][x]` : la premiere dimension est la ligne. Transposee, la carte
    # rendrait un relief en miroir de ses etoiles, sans lever d'erreur.
    # / Rows first; transposed, the relief silently mirrors its stars.
    grille = models.JSONField(default=list, blank=True, verbose_name=_("grille de densité"))
    regions = models.JSONField(default=list, blank=True, verbose_name=_("régions"))
    calcule_le = models.DateTimeField(null=True, blank=True, verbose_name=_("calculé le"))

    class Meta:
        verbose_name = _("ciel")

    def __str__(self):
        return f"ciel de {len(self.regions)} région(s)"
```

- [ ] **Étape 4 : générer la migration**

Run : `make migrations` (passe par `--user`, sinon les fichiers appartiennent à root)
Puis : `docker compose run --rm web python manage.py migrate`
Vérifier le fichier généré : il ne doit contenir **que** `CreateModel` pour `Ciel`. S'il contient autre chose, s'arrêter et le signaler au mainteneur.

- [ ] **Étape 5 : lancer le test et vérifier qu'il passe**

Run : `docker compose run --rm web pytest tests/test_ciel.py -k ciel_neuf -v`
Attendu : PASSÉ.

- [ ] **Étape 6 : proposer le commit**

```
feat(ciel): singleton Ciel, grille et régions
```

---

## Tâche 4 : la tâche Celery et ses quatre déclencheurs

**Fichiers :**
- Modifier : `capsules/tasks.py`
- Modifier : `capsules/views.py` (fonction `retirer_capsule`)
- Modifier : `capsules/admin.py` (actions `retirer` et `republier`)
- Créer : `tests/test_recalcul.py`
- Modifier : `tests/test_enrichissement.py:101-117`

**Interfaces :**
- Consomme : `capsules.ciel.projeter`, `densite`, `regions` (tâches 1-2) ; `capsules.models.Ciel` (tâche 3).
- Produit : `programmer_le_recalcul() -> None` et la tâche `recalculer_le_ciel` (sans argument).

- [ ] **Étape 1 : écrire les tests de la tâche**

```python
"""Le recalcul du ciel : quand il part, quand il ne part pas."""

from unittest.mock import patch

import pytest
from django.core.cache import cache

from capsules.models import Capsule, Ciel, StatutCapsule
from capsules.tasks import VERROU_CIEL, programmer_le_recalcul, recalculer_le_ciel


@pytest.mark.django_db
def test_une_rafale_de_depots_ne_coute_qu_un_calcul():
    with patch.object(recalculer_le_ciel, "apply_async") as enfile:
        for _ in range(5):
            programmer_le_recalcul()

    assert enfile.call_count == 1


def _six_clameurs(reglages):
    """Six clameurs aux vecteurs quelconques : de quoi faire tourner un calcul."""
    import numpy as np

    alea = np.random.default_rng(21)
    for _ in range(6):
        vecteur = alea.normal(0, 1, 1024)
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
            embedding=(vecteur / np.linalg.norm(vecteur)).tolist(),
        )


@pytest.mark.django_db
def test_la_tache_libere_le_verrou_des_son_depart(reglages):
    """Sans cela, une clameur déposée PENDANT le calcul ne programmerait rien
    et resterait sans étoile jusqu'au dépôt suivant — le défaut qui avait fait
    mettre le ciel en sommeil.

    ON REGARDE AU MILIEU DU CALCUL, pas à la fin : un `cache.delete` posé en
    dernière ligne satisferait une vérification finale tout en laissant le
    verrou en place pendant les vingt secondes qui comptent.
    """
    from capsules import ciel

    _six_clameurs(reglages)
    cache.set(VERROU_CIEL, 1, 120)
    verrou_pendant_le_calcul = []

    def _espionner(positions):
        verrou_pendant_le_calcul.append(cache.get(VERROU_CIEL))
        return ciel.densite(positions)

    with patch("capsules.ciel.densite", side_effect=_espionner):
        recalculer_le_ciel()

    assert verrou_pendant_le_calcul == [None], "le verrou tient encore pendant le calcul"


@pytest.mark.django_db(transaction=True)
def test_le_calcul_verrouille_le_ciel_contre_l_autre_worker(reglages):
    """La production tourne à `--concurrency=2` : deux recalculs peuvent partir
    ensemble.

    ON LIT LE SQL RÉELLEMENT ENVOYÉ, et non un appel de méthode : un
    `select_for_update()` dont la requête n'est jamais évaluée ne verrouille
    rien, et un mock d'appel le laisserait passer.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _six_clameurs(reglages)

    with CaptureQueriesContext(connection) as requetes:
        recalculer_le_ciel()

    assert any("FOR UPDATE" in requete["sql"] for requete in requetes), (
        "aucune requête ne verrouille le ciel : deux workers peuvent le calculer ensemble"
    )


@pytest.mark.django_db
def test_le_cache_indisponible_n_empeche_pas_d_enfiler():
    with patch("capsules.tasks.cache.add", side_effect=RuntimeError("redis mort")), \
         patch.object(recalculer_le_ciel, "apply_async") as enfile:
        programmer_le_recalcul()

    assert enfile.call_count == 1


@pytest.mark.django_db
def test_redis_mort_le_retrait_passe_quand_meme(admin_client, capsule_publiee):
    """Le retrait LCEN ne dépend de rien.

    ON PASSE PAR LA VRAIE VUE : c'est elle qui doit survivre à un courtier
    mort, et un appel direct à `programmer_le_recalcul()` ne prouverait rien
    sur le chemin qu'emprunte un auteur pressé de se taire.
    """
    with patch("capsules.tasks.recalculer_le_ciel.apply_async",
               side_effect=RuntimeError("redis mort")):
        reponse = admin_client.post(f"/c/{capsule_publiee.uuid}/retirer")

    assert reponse.status_code in (302, 303)
    capsule_publiee.refresh_from_db()
    assert capsule_publiee.statut == StatutCapsule.RETIREE


@pytest.mark.django_db
def test_le_tsne_ne_tourne_pas_quand_rien_n_attend_de_position(reglages):
    """Un retrait ne doit relancer que la densité et les régions : rien ne
    s'ajoute, la projection n'a aucune raison de tourner."""
    import numpy as np

    alea = np.random.default_rng(11)
    for _ in range(6):
        vecteur = alea.normal(0, 1, 1024)
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
            embedding=(vecteur / np.linalg.norm(vecteur)).tolist(),
        )
    recalculer_le_ciel()          # premier calcul : projette
    avant = {c.uuid: (c.position_x, c.position_y) for c in Capsule.objects.all()}

    with patch("capsules.ciel.projeter") as projection:
        recalculer_le_ciel()      # second : rien n'attend de position

    projection.assert_not_called()
    apres = {c.uuid: (c.position_x, c.position_y) for c in Capsule.objects.all()}
    assert avant == apres
    assert Ciel.get_solo().grille, "la densité, elle, doit avoir été recalculée"


@pytest.mark.django_db
def test_un_vecteur_inexploitable_ne_relance_pas_la_projection_a_vie(reglages):
    """Sinon la règle « projeter s'il manque une position » ne termine jamais :
    la capsule abîmée n'en reçoit pas, et rappelle le t-SNE à chaque calcul."""
    import numpy as np

    alea = np.random.default_rng(12)
    for numero in range(6):
        vecteur = [0.0] * 1024 if numero == 0 else list(alea.normal(0, 1, 1024))
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE,
            duree_secondes=30, embedding=vecteur,
        )
    recalculer_le_ciel()

    with patch("capsules.ciel.projeter") as projection:
        recalculer_le_ciel()

    projection.assert_not_called()
    abimee = Capsule.objects.filter(erreur_enrichissement__icontains="vecteur")
    assert abimee.exists(), "la capsule au vecteur nul doit être signalée"


@pytest.mark.django_db
def test_moins_de_trois_clameurs_ecrit_un_ciel_vide(reglages):
    import numpy as np

    alea = np.random.default_rng(13)
    # ELLE PORTE DEJA UNE POSITION, d'un calcul precedent : sans cela,
    # l'assertion « plus aucune position » serait vraie avant meme l'appel.
    Capsule.objects.create(
        reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
        embedding=list(alea.normal(0, 1, 1024)), position_x=0.5, position_y=0.5,
    )
    Ciel.objects.update_or_create(defaults={"grille": [[1.0]], "regions": [{"nom": "vieux"}]})

    recalculer_le_ciel()

    objet = Ciel.get_solo()
    assert objet.grille == [] and objet.regions == []
    assert not Capsule.objects.exclude(position_x=None).exists()


@pytest.mark.django_db
def test_l_action_d_admin_retirer_programme_un_recalcul(admin_client, capsule_publiee):
    """Les actions d'admin passent par `queryset.update()`, qui n'émet aucun
    signal : sans appel explicite, une clameur retirée resterait au ciel."""
    with patch("capsules.admin.programmer_le_recalcul") as programme:
        admin_client.post(
            "/admin/capsules/capsule/",
            {"action": "retirer", "_selected_action": [str(capsule_publiee.uuid)]},
            follow=True,
        )

    programme.assert_called_once()
```

- [ ] **Étape 2 : lancer les tests et vérifier qu'ils échouent**

Run : `docker compose run --rm web pytest tests/test_recalcul.py -v`
Attendu : ÉCHEC — `ImportError: cannot import name 'VERROU_CIEL'`.

- [ ] **Étape 3 : écrire la tâche et le programmateur**

Dans `capsules/tasks.py`, ajouter `from django.core.cache import cache` aux imports, puis :

```python
VERROU_CIEL = "ciel:programme"

# DEUX MINUTES. Assez pour qu'une rafale de depots ne coute qu'un calcul et que
# les tags machine soient arrives, assez peu pour qu'une clameur neuve trouve
# son etoile avant que son auteur ne referme la page.
# / Two minutes: one computation per burst, and a fresh star before the visitor
#   closes the page.
DELAI_RECALCUL = 120


def programmer_le_recalcul() -> None:
    """Programme un recalcul du ciel, au plus un par fenetre.

    N'ECHOUE JAMAIS. Elle est appelee depuis le retrait d'une clameur, qui est
    une obligation legale : ni un cache muet ni un courtier mort ne doivent
    empecher un auteur de faire taire sa voix.
    / Never fails: it is called from the LCEN takedown path.
    """
    try:
        if not cache.add(VERROU_CIEL, 1, DELAI_RECALCUL):
            return
    except Exception:
        logger.warning("cache indisponible : recalcul du ciel enfilé sans verrou")

    try:
        recalculer_le_ciel.apply_async(countdown=DELAI_RECALCUL)
    except Exception:
        logger.exception("enqueue du recalcul du ciel impossible")


@shared_task
def recalculer_le_ciel() -> str:
    """Recalcule les positions, le relief et les regions.

    SANS ARGUMENT, donc toujours a partir de l'etat frais : la tache est
    idempotente, ce qu'exige `acks_late`.
    / No argument: always recomputed from fresh state, as acks_late demands.
    """
    # LE VERROU TOMBE EN PREMIER. Une clameur deposee pendant le calcul doit
    # pouvoir programmer le suivant ; sinon elle attend un depot de plus pour
    # exister — le defaut meme qui avait fait mettre le ciel en sommeil.
    # / Released first: a clameur arriving mid-computation must re-arm.
    try:
        cache.delete(VERROU_CIEL)
    except Exception:
        logger.warning("cache indisponible : verrou du ciel non libéré")

    # Import paresseux : `tasks` est importe par `publication`, et numpy n'a
    # rien a faire dans un worker web. / Lazy: numpy has no place in a web worker.
    import numpy as np

    from capsules import ciel as calcul
    from capsules.models import Ciel

    with transaction.atomic():
        # `get_solo()` d'abord : on ne verrouille pas une ligne qui n'existe pas.
        # / get_solo() first: there is no row to lock before the first run.
        objet = Ciel.get_solo()
        Ciel.objects.select_for_update().filter(pk=objet.pk).first()

        capsules = list(
            Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
            .exclude(embedding=None)
            .prefetch_related("tags_de_capsule__tag")
        )
        vecteurs = (
            np.vstack([np.asarray(c.embedding, dtype=float) for c in capsules])
            if capsules else np.empty((0, 1024))
        )
        exploitables = (
            np.isfinite(vecteurs).all(axis=1) & (np.linalg.norm(vecteurs, axis=1) > 0)
            if len(capsules) else np.zeros(0, dtype=bool)
        )

        # UN VECTEUR ABIME EST SIGNALE DANS L'ADMIN. C'est le masque
        # `exploitables` qui l'ecarte du calcul, juste au-dessus ; ce message
        # existe pour que l'operateur sache pourquoi cette clameur n'a pas
        # d'etoile, au lieu de la chercher en vain dans le ciel.
        # / The mask already excludes it; this message tells the operator why.
        for capsule, garde in zip(capsules, exploitables):
            if not garde and "vecteur" not in capsule.erreur_enrichissement:
                capsule.erreur_enrichissement = (
                    f"{ETAPE_EMBEDDING} : vecteur inexploitable, pas d'étoile"
                )
                capsule.save(update_fields=["erreur_enrichissement"])

        retenues = [c for c, garde in zip(capsules, exploitables) if garde]
        vecteurs = vecteurs[exploitables] if len(capsules) else vecteurs

        if len(retenues) < 3:
            Capsule.objects.exclude(position_x=None).update(position_x=None, position_y=None)
            objet.grille, objet.regions = [], []
            objet.calcule_le = timezone.now()
            objet.save(update_fields=["grille", "regions", "calcule_le"])
            return "trop peu"

        # LE T-SNE NE TOURNE QUE SI QUELQUE CHOSE ATTEND UNE POSITION. Un
        # retrait ne fait rien entrer : recalculer la projection deplacerait
        # toutes les etoiles pour rien. / Only project when a star is missing.
        if any(c.position_x is None for c in retenues):
            positions = calcul.projeter(vecteurs)
            for capsule, (x, y) in zip(retenues, positions):
                capsule.position_x, capsule.position_y = float(x), float(y)
            Capsule.objects.bulk_update(
                retenues, ["position_x", "position_y"], batch_size=200
            )
        else:
            positions = np.array([[c.position_x, c.position_y] for c in retenues])

        grille = calcul.densite(positions)
        if not np.isfinite(grille).all():
            # SEULE BARRIERE CONTRE LE NAN : `json_script` le serialise tel
            # quel, et `JSON.parse` casse alors sans un mot dans la console.
            # / json_script emits NaN verbatim and JSON.parse dies silently.
            logger.error("grille non finie : ciel laissé vide")
            objet.grille, objet.regions = [], []
        else:
            tags = [
                [(lien.tag.nom, lien.origine) for lien in c.tags_de_capsule.all()]
                for c in retenues
            ]
            objet.grille = np.round(grille, 3).tolist()
            objet.regions = calcul.regions(grille, positions, tags)

        # Les positions des capsules qui ne sont plus projetees disparaissent :
        # une retiree republiee ne doit pas revenir a la place d'une projection
        # d'avant. / Stale positions go, or a republished capsule lands wrong.
        Capsule.objects.exclude(
            uuid__in=[c.uuid for c in retenues]
        ).exclude(position_x=None).update(position_x=None, position_y=None)

        objet.calcule_le = timezone.now()
        objet.save(update_fields=["grille", "regions", "calcule_le"])

    return "ok"
```

- [ ] **Étape 4 : brancher les quatre déclencheurs**

1. Dans `taguer` et `embarquer`, avant le `return "ok"` final : `programmer_le_recalcul()`.
2. Dans `transcrire`, remettre `embarquer` en file à côté de `taguer` — remplacer le commentaire « UNE SEULE SUITE DEPUIS LE 2026-09-01 » par une explication du retour des deux suites en parallèle, et ajouter `_enfiler(embarquer, uuid_capsule)`.
3. Dans `capsules/views.py`, `retirer_capsule`, après le `capsule.save(update_fields=["statut"])` : `programmer_le_recalcul()` (importée depuis `capsules.tasks`, dans la fonction pour éviter un import circulaire).
4. Dans `capsules/admin.py`, **import en tête de module** — `from capsules.tasks import programmer_le_recalcul` — et non paresseux dans la fonction comme le fait `rejouer_l_enrichissement` : c'est ce que le test de l'étape 1 remplace par un mock, et il n'y a pas de cycle (`tasks` n'importe jamais `admin`). Appeler `programmer_le_recalcul()` après le `queryset.update(...)` des actions `retirer` **et** `republier`, avec un commentaire disant pourquoi l'appel est explicite : `update()` n'émet aucun signal.

- [ ] **Étape 5 : retourner le test du sommeil**

Dans `tests/test_enrichissement.py`, remplacer `test_l_embedding_ne_part_plus_derriere_la_transcription` par :

```python
@pytest.mark.django_db
def test_les_deux_suites_partent_derriere_la_transcription(capsule_a_transcrire):
    """Le titre, les mots-clés et le vecteur, en parallèle.

    Le vecteur est ce qui donne une étoile à la clameur : sans lui, elle est
    dans la liste et absente du ciel.
    """
    lances = []
    with patch("capsules.tasks.transcrire_le_fichier", return_value=TRANSCRIPTION), \
         patch("capsules.tasks.diffuser_la_transcription"), \
         patch.object(taguer, "delay", lambda u: lances.append("taguer")), \
         patch.object(embarquer, "delay", lambda u: lances.append("embarquer")):
        transcrire(str(capsule_a_transcrire.uuid))

    assert sorted(lances) == ["embarquer", "taguer"]
```

- [ ] **Étape 6 : lancer la suite complète**

Run : `make test`
Attendu : tout passe. Les échecs attendus à ce stade concernent la vue et les gabarits (tâches 6-7) s'ils sont déjà touchés ; sinon, zéro échec.

- [ ] **Étape 7 : redémarrer le worker et proposer le commit**

Run : `docker compose restart celery` (le worker ne recharge pas le code)

```
feat(ciel): recalcul par Celery, avec verrou et déclencheurs
```

---

## Tâche 5 : la commande `projeter_la_constellation`

**Fichiers :**
- Réécrire : `capsules/management/commands/projeter_la_constellation.py`
- Modifier : `tests/test_constellation.py`

**Interfaces :**
- Consomme : `capsules.tasks.recalculer_le_ciel` (tâche 4).
- Produit : la commande, qui affiche le nombre de clameurs projetées et la fidélité.

- [ ] **Étape 1 : adapter les tests existants**

Dans `tests/test_constellation.py` :
- `test_une_clameur_de_plus_ne_retourne_pas_le_ciel` (ligne 167) et `test_la_fidelite_ne_flatte_pas_un_corpus_minuscule` (ligne 235) **instancient `Command()`** et appellent `._pca` / `._fidelite`. Ces méthodes n'existent plus : supprimer l'import de `Command` et les deux instanciations, et appeler `ciel.pca(...)` et `ciel.fidelite(...)` directement.
- `test_deux_positions_voisines_donnent_des_teintes_voisines` et `test_deux_amas_opposes_se_distinguent_sans_quitter_la_famille_chaude` testent `_teinte_de_la_position`, qui disparaît (tâche 6) : les **supprimer**, remplacés par les tests de couleur de la tâche 6.
- Ajouter : après la commande, `Ciel.get_solo().grille` n'est pas vide.

- [ ] **Étape 2 : lancer et vérifier l'échec**

Run : `docker compose run --rm web pytest tests/test_constellation.py -v`
Attendu : ÉCHEC sur `Command()._pca`, qui n'existe plus — l'algorithme vit dans `capsules.ciel` depuis la tâche 1.

- [ ] **Étape 3 : réécrire la commande**

Elle devient une enveloppe : elle appelle `recalculer_le_ciel()` **en synchrone** (pas `.delay()`), puis affiche le compte et la fidélité calculée par `ciel.fidelite`. Son option `--tout` est **supprimée** : projeter les capsules retirées les ferait entrer dans la densité. Le grand commentaire d'en-tête (pourquoi les positions sont stockées, pourquoi t-SNE, pourquoi l'initialisation par la PCA, pourquoi la variance n'est plus affichée) **déménage dans `capsules/ciel.py`** : c'est là que vit désormais l'algorithme.

- [ ] **Étape 4 : lancer les tests**

Run : `docker compose run --rm web pytest tests/test_constellation.py tests/test_ciel.py -v`
Attendu : tout passe.

- [ ] **Étape 5 : vérifier en vrai sur le corpus de démonstration**

Run : `docker compose run --rm web python manage.py projeter_la_constellation`
Attendu : « 100 clameurs projetées », une fidélité affichée supérieure à 90 %, et aucune erreur.

- [ ] **Étape 6 : proposer le commit**

```
refactor(ciel): la commande appelle le module et écrit le Ciel
```

---

## Tâche 6 : la vue, le contexte et la fin du code dormant

**Fichiers :**
- Modifier : `capsules/views.py`
- Supprimer : `capsules/templates/capsules/constellation.html`, `capsules/static/capsules/constellation.js`
- Modifier : `tests/test_liste.py`
- Modifier : `tests/test_temps_reel.py:32` — **il lit `data-x` dans la page**, que cette tâche retire. Sans quoi le « tout passe » de cette tâche et de la suivante est faux.

**Interfaces :**
- Consomme : `Ciel` (tâche 3).
- Produit : le contexte `{"clameurs", "nombre", "nombre_en_tout", "recherche", "invitation", "pour_htmx", "grille", "regions", "etoiles"}` ; chaque clameur porte `a_une_etoile` ; `_teinte_de_la_duree(secondes: int) -> int`.

- [ ] **Étape 1 : écrire les tests de la vue**

```python
@pytest.mark.django_db
def test_la_page_porte_le_relief_et_les_etoiles(client, corpus_pret):
    page = client.get("/").content.decode()

    assert 'id="donnees-grille"' in page
    assert 'id="donnees-regions"' in page
    assert 'id="donnees-etoiles"' in page


@pytest.mark.django_db
def test_les_etoiles_ne_dependent_pas_de_la_recherche(client, corpus_pret):
    """Le ciel montre le corpus, pas le résultat. Sans cela, `/?q=x` partagé
    rendrait une carte amputée de tout ce que la recherche écarte."""
    import json
    import re

    def etoiles(reponse):
        brut = re.search(
            r'id="donnees-etoiles"[^>]*>(.*?)</script>', reponse.content.decode(), re.S
        ).group(1)
        return json.loads(brut)

    assert len(etoiles(client.get("/?q=zzzz"))) == len(etoiles(client.get("/")))
    assert len(etoiles(client.get("/"))) > 0


@pytest.mark.django_db
def test_une_clameur_sans_vecteur_figure_dans_la_liste_sans_etoile(client, corpus):
    page = client.get("/").content.decode()

    assert "sans-etoile" in page, "la fiche sans position doit porter sa pastille creuse"


@pytest.mark.django_db
def test_la_teinte_suit_la_duree(client):
    from capsules.views import _teinte_de_la_duree

    breve, longue = _teinte_de_la_duree(5), _teinte_de_la_duree(170)
    assert breve != longue
    for teinte in (breve, longue):
        assert 0 <= teinte < 360
        assert teinte >= 350 or teinte <= 100, "la teinte quitte l'arc chaud"
```

- [ ] **Étape 2 : lancer et vérifier l'échec**

Run : `docker compose run --rm web pytest tests/test_liste.py -v`
Attendu : ÉCHEC — les `json_script` n'existent pas.

- [ ] **Étape 3 : modifier la vue `liste`**

- Ajouter au contexte, **hors du rendu HTMX** (le fragment `_resultats.html` ne porte aucune donnée de ciel) :

```python
    ciel = Ciel.get_solo()
    etoiles = [
        {
            "uuid": str(capsule.uuid),
            "x": round(capsule.position_x, 4), "y": round(capsule.position_y, 4),
            "ecoutes": capsule.nombre_ecoutes, "duree": capsule.duree_secondes,
            "voix": _nombre_de_voix(capsule),
            # L'HEURE SEULE, PAS LA DATE, ET EN HEURE LOCALE. Elle sert a
            # colorer « jour » ou « nuit » : lue en UTC, une clameur deposee a
            # vingt-et-une heures en ete passerait pour une clameur de jour.
            # La fraicheur, elle, se lit dans l'ORDRE de cette liste, qui part
            # de la plus recente.
            # / Local hour: read in UTC, an evening clameur reads as daylight.
            "heure": (
                timezone.localtime(capsule.publiee_le).hour if capsule.publiee_le else 12
            ),
            "titre": capsule.titre or capsule.pseudo or str(_("Anonyme")),
        }
        # TOUTES LES ETOILES, SANS EGARD POUR LA RECHERCHE. Le relief decrit le
        # corpus ; filtrer le ciel rendrait une carte amputee a qui partage un
        # lien de recherche. / The sky shows the corpus, never the result.
        for capsule in Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
        .exclude(position_x=None).order_by("-publiee_le")[:PLAFOND_DE_LA_LISTE]
    ]
```

- Ajouter `_nombre_de_voix(capsule)` : le nombre de `speaker` distincts dans `transcription_raw["segments"]`, au minimum 1.
- Remplacer `_teinte_de_la_capsule` et `_teinte_de_la_position` par `_teinte_de_la_duree(secondes)` : `350 + min(1, secondes / 180) * 110`, modulo 360. `decrire_une_clameur` expose `teinte` (durée) et **`a_une_etoile`** ; `x` et `y` disparaissent de la fiche, qui n'en a plus besoin.
- Supprimer la vue `constellation` et `PLAFOND_CONSTELLATION`.

- [ ] **Étape 4 : supprimer le code dormant**

```bash
rm capsules/templates/capsules/constellation.html capsules/static/capsules/constellation.js
```
Vérifier qu'aucune référence ne subsiste : `grep -rn "constellation.html\|constellation.js\|PLAFOND_CONSTELLATION" --include=*.py --include=*.html .`

- [ ] **Étape 5 : retourner le test du temps réel**

`tests/test_temps_reel.py:32`, nommé **`test_les_positions_sortent_avec_un_point_decimal`**, vérifie que les positions sortent sans virgule décimale en lisant `data-x` dans la page. Ces attributs disparaissent : les coordonnées voyagent désormais dans `donnees-etoiles`. Remplacer le corps de ce test — garder sa fixture `corpus_pret` — par :

```python
@pytest.mark.django_db
def test_les_positions_sortent_avec_un_point_decimal(client, corpus_pret):
    """En français, Django rend les flottants avec une virgule : `Number()`
    donnait alors NaN, et les cent étoiles disparaissaient sans une erreur.

    `json_script` ne localise jamais — c'est précisément pourquoi les données
    du ciel passent par lui plutôt que par des attributs.
    """
    import json
    import re

    page = client.get("/").content.decode()
    brut = re.search(r'id="donnees-etoiles"[^>]*>(.*?)</script>', page, re.S).group(1)

    for etoile in json.loads(brut):
        assert isinstance(etoile["x"], float) and isinstance(etoile["y"], float)
```

- [ ] **Étape 6 : lancer la suite**

Run : `make test`
Attendu : les tests de gabarit échouent encore (tâche 7) ; ceux de la vue et du temps réel passent.

- [ ] **Étape 7 : proposer le commit**

```
feat(ciel): contexte du double écran, teinte par durée, fin du code dormant
```

---

## Tâche 7 : le gabarit du double écran

**Fichiers :**
- Modifier : `capsules/templates/capsules/liste.html`
- Modifier : `capsules/templates/capsules/_fiche.html`

**Interfaces :**
- Consomme : le contexte de la tâche 6.
- Produit — **toutes les ancres que le JavaScript des tâches 8 à 11 exige, aucune de moins** :
  - `#panneau-liste` : le conteneur **qui défile** sur le bureau (`overflow-y: auto`) ;
  - `#resultats`, dans son `<div hx-ext="ws">` : ce que HTMX remplace, inchangé ;
  - `#ciel` : le SVG, `viewBox="0 0 1000 1000"`, contenant dans cet ordre les groupes `#relief`, `#traces`, `#etoiles`, `#etiquettes` ;
  - les trois `json_script` `donnees-grille`, `donnees-regions`, `donnees-etoiles`, **hors de `#resultats`** ;
  - les commandes : `#choix-couleur` (trois boutons `data-encodage="duree|voix|heure"`, celui de la durée à `aria-pressed="true"`), `#legende`, et `#deriver` portant `data-depart` et `data-arret` (les deux libellés traduits) ;
  - `#annonce-derive` : un `<p class="sr-only" aria-live="polite">`, et la classe `.sr-only` dans le CSS si elle n'existe pas déjà ;
  - `window.URL_ECOUTE` et `window.JETON_CSRF`, posés par un `<script>` comme le faisait l'ancien `constellation.html` ;
  - le CSS de `.etiquette` (halo `paint-order: stroke`), `.etoile.pale` (opacité 0,35), `.etoile.choisie`, `.trace`, `.clameur.sans-etoile .pastille-liste`.

- [ ] **Étape 1 : la structure**

Dans `liste.html`, le `{% block contenu %}` devient le double écran. **L'en-tête, le bouton d'invitation, son `<dialog>` et le formulaire de recherche sont déplacés tels quels** dans le panneau de gauche — on ne les réécrit pas.

```django
{% block contenu %}
<div class="double-ecran">
  <section id="panneau-liste" class="panneau-liste" aria-label="{% translate 'Liste des clameurs' %}">
    {# En-tête, invitation et formulaire de recherche : repris sans modification. #}
    <header class="entete">
      <h1>{% translate "Les clameurs" %}</h1>
      {% include "capsules/_compte.html" %}
    </header>

    {% if invitation %}{# … le bouton et le <dialog> existants, inchangés … #}{% endif %}

    {# Le WebSocket vit SUR LE PARENT, jamais sur ce que HTMX remplace : une
       transcription qui arrive pendant une recherche couperait la connexion. #}
    <form class="chercher" role="search" action="{% url 'capsules:liste' %}" method="get">
      {# … le champ et son indicateur, inchangés … #}
    </form>
    <div hx-ext="ws" ws-connect="/ws/constellation">
      <div id="resultats">{% include "capsules/_resultats.html" %}</div>
    </div>
  </section>

  <section class="panneau-ciel" aria-label="{% translate 'Le ciel des clameurs' %}">
    {# Les quatre groupes sont dans CET ordre : le relief au fond, les
       étiquettes au-dessus de tout. Un ordre différent enterre les noms. #}
    <svg id="ciel" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet"
         role="group" aria-label="{% translate 'Chaque point est une clameur' %}">
      <g id="relief"></g>
      <g id="traces"></g>
      <g id="etoiles"></g>
      <g id="etiquettes"></g>
    </svg>

    <div class="commandes">
      <p class="titre-commande">{% translate "Colorer par" %}</p>
      <div class="choix" id="choix-couleur"
           data-legende-duree="{% translate 'Couleur : durée · plus clair, plus récent' %}"
           data-legende-voix="{% translate 'Couleur : nombre de voix · plus clair, plus récent' %}"
           data-legende-heure="{% translate 'Couleur : heure du dépôt · plus clair, plus récent' %}">
        <button type="button" data-encodage="duree" aria-pressed="true">{% translate "Durée" %}</button>
        <button type="button" data-encodage="voix" aria-pressed="false">{% translate "Voix" %}</button>
        <button type="button" data-encodage="heure" aria-pressed="false">{% translate "Heure" %}</button>
      </div>
      <p class="legende" id="legende"></p>

      <button type="button" class="deriver" id="deriver" aria-pressed="false"
              data-depart="{% translate 'Laisser dériver' %}"
              data-arret="{% translate 'Arrêter la dérive' %}">
        {% translate "Laisser dériver" %}
      </button>
      {# Ce que la dérive dit à qui n'a pas l'écran. #}
      <p id="annonce-derive" class="sr-only" aria-live="polite"></p>
    </div>
  </section>
</div>

{# HORS DE #resultats : HTMX les emporterait au premier swap, et le ciel
   perdrait ses données à la première lettre tapée dans la recherche. #}
{{ grille|json_script:"donnees-grille" }}
{{ regions|json_script:"donnees-regions" }}
{{ etoiles|json_script:"donnees-etoiles" }}
{% endblock %}

{# `base.html` pose un pied de page sous `main` : garde, il ferait dépasser
   les 100dvh du double écran et la page défilerait sur le bureau. #}
{% block pied %}{% endblock %}
```

- [ ] **Étape 2 : le CSS**

Ajouté au `{% block styles %}` existant, dont les styles de fiche, de recherche et d'invitation **restent inchangés** :

```css
  /* Le double écran prend toute la page : `base.html` cale `main` à 38rem,
     ce qui n'a plus de sens ici. */
  main { max-width: none; padding: 0; }

  .double-ecran {
    display: grid; grid-template-columns: minmax(320px, 31rem) 1fr;
    height: 100dvh; overflow: hidden;
  }

  /* `position: relative` : c'est LUI qui sert de repère à `offsetTop`. Sans
     lui, la position d'une fiche se mesure depuis le haut du document et le
     défilement piloté par le ciel tombe à côté. */
  .panneau-liste {
    position: relative; overflow-y: auto;
    border-right: 1px solid var(--color-trait);
    padding: var(--space-lg); min-height: 0;
    scrollbar-width: thin; scrollbar-color: var(--color-glissiere) transparent;
  }

  .panneau-ciel { position: relative; min-height: 0; background: var(--color-paper); }
  #ciel { width: 100%; height: 100%; display: block; touch-action: manipulation; }
  #ciel .etoile { cursor: pointer; transition: opacity var(--dur-court) var(--ease-out); }
  /* 0,35 et non 0,1 : une étoile de deux pixels disparaîtrait tout à fait. */
  #ciel .etoile.pale { opacity: 0.35 !important; }
  #ciel .etoile.choisie { stroke: var(--color-ink); stroke-width: 2.5; }

  /* Le halo n'est pas décoratif : c'est lui qui tient le contraste d'un nom
     posé sur les courbes claires du relief. */
  #ciel .etiquette {
    font-family: var(--font-display); font-weight: 700; fill: var(--color-ink);
    paint-order: stroke; stroke: oklch(0.19 0.022 45 / 0.75); stroke-width: 4px;
    cursor: pointer; user-select: none;
  }
  #ciel .etiquette.machine {
    font-style: italic; font-weight: 500; fill: var(--color-ink-tenu);
  }
  #ciel .trace {
    fill: none; stroke: var(--color-ambre); stroke-width: 1.6;
    stroke-linecap: round; stroke-linejoin: round; opacity: 0.75;
  }

  .commandes {
    position: absolute; left: var(--space-md); bottom: var(--space-md);
    display: flex; flex-direction: column; gap: var(--space-xs);
    background: oklch(0.19 0.022 45 / 0.86); border: 1px solid var(--color-trait);
    border-radius: var(--radius-md); padding: var(--space-sm);
    max-width: min(20rem, calc(100% - 2 * var(--space-md)));
  }
  .titre-commande {
    font-size: var(--text-xs); text-transform: uppercase;
    letter-spacing: var(--tracking-label); color: var(--color-ink-tenu); margin: 0;
  }
  .choix { display: flex; gap: var(--space-2xs); flex-wrap: wrap; }
  .choix button {
    padding: var(--space-2xs) var(--space-sm); border-radius: var(--radius-pilule);
    border: 1px solid var(--color-trait); background: transparent;
    color: var(--color-ink-doux); font: inherit; font-size: var(--text-sm); cursor: pointer;
  }
  .choix button[aria-pressed="true"] {
    background: var(--color-ink); color: var(--color-sur-accent); border-color: var(--color-ink);
  }
  .legende { font-size: var(--text-xs); color: var(--color-ink-tenu); margin: 0; }
  .deriver {
    padding: var(--space-2xs) var(--space-sm); border-radius: var(--radius-pilule);
    border: var(--rule-porte) solid var(--color-braise); background: var(--color-braise);
    color: var(--color-sur-accent); font: inherit; font-weight: 600;
    font-size: var(--text-sm); cursor: pointer;
    box-shadow: 3px 3px 0 0 var(--color-braise-ombre);
    transition: transform var(--dur-court) var(--ease-out),
                box-shadow var(--dur-court) var(--ease-out);
  }
  .deriver:hover { transform: translate(3px, 3px); box-shadow: 0 0 0 0 var(--color-braise-ombre); }

  /* Lu par les lecteurs d'écran, jamais affiché. */
  .sr-only {
    position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip-path: inset(50%); white-space: nowrap;
  }

  /* Une clameur sans vecteur est dans la liste, sans étoile : la pastille
     creuse le dit, au lieu de la faire passer pour une clameur placée. */
  .clameur.sans-etoile .pastille-liste {
    background: transparent; border: 2px solid var(--color-ink-tenu);
  }

  @media (max-width: 800px) {
    .double-ecran { display: block; height: auto; overflow: visible; }
    .panneau-liste { border-right: 0; overflow: visible; }
    .panneau-ciel {
      position: sticky; top: 0; z-index: 2; height: 50dvh;
      border-bottom: 1px solid var(--color-trait);
      transition: height var(--dur-moyen) var(--ease-out);
    }
    .panneau-ciel.replie { height: 22dvh; }
    .commandes { left: var(--space-xs); bottom: var(--space-xs); padding: var(--space-xs); }
  }

  @media (prefers-reduced-motion: reduce) {
    .panneau-ciel { transition: none; }
  }
```

- [ ] **Étape 3 : les scripts**

Dans `{% block scripts %}`, avant `partage.js` : `window.URL_ECOUTE` et `window.JETON_CSRF` (repris de l'ancien `constellation.html`), puis **`d3-array` avant `d3-contour`**, puis `ciel.js` en `defer`.

- [ ] **Étape 4 : modifier la fiche**

Dans `_fiche.html` : **retirer** `data-choisir`, `data-x`, `data-y` et `data-teinte` ; ajouter `class="clameur sans-etoile"` quand `clameur.a_une_etoile` est faux. **Ne pas ajouter d'autres `data-*`** : le JavaScript lit tout dans `donnees-etoiles`, et des attributs que personne ne lit sont du poids mort sur six cents fiches. Le bloc `{% localize off %}` reste.

- [ ] **Étape 3 : vérifier à l'œil**

Run : `make start`, ouvrir `http://localhost:8000/`
Attendu : la liste et le panneau du ciel (vide, le JS n'existe pas encore) ; la recherche fonctionne toujours ; aucune erreur en console.

- [ ] **Étape 4 : lancer la suite**

Run : `make test`
Attendu : tout passe.

- [ ] **Étape 5 : proposer le commit**

```
feat(ciel): gabarit du double écran et fiche adaptée
```

---

## Tâche 8 : le relief et les étiquettes

**Fichiers :**
- Créer : `capsules/static/capsules/vendor/d3-array-3.2.4.min.js`, `capsules/static/capsules/vendor/d3-contour-4.0.2.min.js`
- Créer : `capsules/static/capsules/ciel.js`
- Modifier : `capsules/templates/capsules/liste.html` (balises `<script>`)

**Interfaces :**
- Consomme : `donnees-grille`, `donnees-regions` (tâche 7).
- Produit : les fonctions internes `dessinerLeRelief()` et `poserLesEtiquettes()`.

- [ ] **Étape 1 : déposer les bibliothèques**

```bash
curl -o capsules/static/capsules/vendor/d3-array-3.2.4.min.js \
  https://cdn.jsdelivr.net/npm/d3-array@3.2.4/dist/d3-array.min.js
curl -o capsules/static/capsules/vendor/d3-contour-4.0.2.min.js \
  https://cdn.jsdelivr.net/npm/d3-contour@4.0.2/dist/d3-contour.min.js
```
Tailles attendues : 17 204 et 5 729 octets. **`d3-array` se charge en premier** : le paquet UMD de `d3-contour` s'attend à le trouver.

- [ ] **Étape 2 : écrire l'en-tête du module et le relief**

```javascript
/*
 * Le ciel : un relief de densite, des regions nommees, des etoiles.
 *
 * LES DONNEES VIENNENT DE `json_script`, JAMAIS DU DOM. HTMX remplace
 * `#resultats` a chaque frappe de la recherche, et une adresse partagee avec
 * `?q=` ne rend qu'une poignee de fiches : un ciel construit sur ces fiches
 * serait ampute de tout ce que la recherche ecarte.
 * / Data comes from json_script: HTMX swaps the list on every keystroke.
 */

(function () {
  "use strict";

  const svg = document.getElementById("ciel");
  if (!svg) return;

  const ESPACE = "http://www.w3.org/2000/svg";
  const CASES = 96;
  const COTE = 1000;
  const NIVEAUX = 10;

  const lire = (id) => JSON.parse(document.getElementById(id).textContent);
  const grille = lire("donnees-grille");
  const lesRegions = lire("donnees-regions");
  const CORPUS = lire("donnees-etoiles");

  function dessinerLeRelief() {
    if (!grille.length) return;      // ciel vide : ni relief ni noms

    const seuils = [];
    for (let n = 1; n <= NIVEAUX; n++) seuils.push(n / (NIVEAUX + 1));

    const contours = d3.contours().size([CASES, CASES]).thresholds(seuils)(grille.flat());
    const echelle = COTE / CASES;
    const fragment = document.createDocumentFragment();

    contours.forEach((contour, rang) => {
      const chemin = document.createElementNS(ESPACE, "path");
      chemin.setAttribute("d", versChemin(contour, echelle));
      // Les anneaux interieurs sont des TROUS, pas des iles : sans `evenodd`,
      // une cuvette cernee par un massif se remplit comme un sommet.
      // / Inner rings are holes: without evenodd a basin fills like a peak.
      chemin.setAttribute("fill-rule", "evenodd");
      // Les hauteurs s'eclaircissent dans les tons du papier : la couleur
      // reste reservee aux etoiles.
      // / Heights lighten within the paper tones; colour belongs to the stars.
      const clarte = 0.205 + (rang / NIVEAUX) * 0.105;
      chemin.setAttribute("fill", `oklch(${clarte.toFixed(3)} 0.028 45)`);
      chemin.setAttribute("stroke", "oklch(0.94 0.016 70 / 0.10)");
      chemin.setAttribute("stroke-width", "1");
      chemin.setAttribute("vector-effect", "non-scaling-stroke");
      fragment.appendChild(chemin);
    });
    document.getElementById("relief").appendChild(fragment);
  }

  function versChemin(contour, echelle) {
    /*
     * d3-contour rend du GeoJSON : on ecrit les anneaux a la main plutot que
     * d'embarquer d3-geo, cinquante kilo-octets pour cette boucle.
     * L'AXE Y N'EST PAS INVERSE : la grille et le ciel ont la meme orientation.
     * / Hand-written rings instead of d3-geo; the y axis is not flipped.
     */
    let d = "";
    for (const polygone of contour.coordinates) {
      for (const anneau of polygone) {
        anneau.forEach((point, rang) => {
          d += (rang === 0 ? "M" : "L")
             + (point[0] * echelle).toFixed(1) + "," + (point[1] * echelle).toFixed(1);
        });
        d += "Z";
      }
    }
    return d;
  }
```

- [ ] **Étape 3 : écrire les étiquettes**

```javascript
  function poserLesEtiquettes() {
    const groupe = document.getElementById("etiquettes");
    groupe.replaceChildren();
    const cadre = svg.getBoundingClientRect();
    if (!cadre.width || !lesRegions.length) return;

    /*
     * L'ECHELLE SE LIT DANS LA MATRICE DU SVG, PAS DANS LA LARGEUR DU CADRE.
     * Avec `preserveAspectRatio` a `meet`, le dessin est mis a l'echelle par le
     * PLUS PETIT des deux rapports et centre : sur un panneau large et court,
     * `viewBox.width / cadre.width` sous-estime l'echelle, et les etiquettes
     * tombent a huit pixels au lieu de quatorze.
     * / Under `meet` the drawing scales by the smaller ratio; the frame width
     *   alone lies about it.
     */
    const matrice = svg.getScreenCTM();
    if (!matrice) return;
    const parPixel = 1 / matrice.a;
    const posees = [];

    for (const region of lesRegions) {
      const taille = (region.poids >= 12 ? 17.5 : region.poids >= 6 ? 15.5 : 13.5) * parPixel;
      const texte = document.createElementNS(ESPACE, "text");
      texte.setAttribute("x", (region.x * COTE).toFixed(1));
      texte.setAttribute("y", (region.y * COTE - 14 * parPixel).toFixed(1));
      texte.setAttribute("text-anchor", "middle");
      texte.setAttribute("font-size", taille.toFixed(1));
      texte.setAttribute(
        "class", "etiquette" + (region.origine === "machine" ? " machine" : "")
      );
      texte.textContent = region.nom;

      if (region.origine === "machine") {
        // La machine propose, elle n'affirme pas : l'italique le dit a l'oeil,
        // ce titre le dit aux lecteurs d'ecran.
        // / The machine suggests; italics say it to the eye, this to a reader.
        const titre = document.createElementNS(ESPACE, "title");
        titre.textContent = `${region.nom} — mot-clé proposé par la machine`;
        texte.appendChild(titre);
      }

      texte.addEventListener("click", (evenement) => {
        // SANS CELA, LE CLIC CONTINUE JUSQU'AU CIEL, qui choisit l'etoile la
        // plus proche du nom — une etoile quelconque, a quatorze pixels au
        // dessus du sommet. / Otherwise the sky also picks a star underneath.
        evenement.stopPropagation();
        const champ = document.querySelector('.chercher input[name="q"]');
        champ.value = region.nom;
        // `input` et non `change` : c'est l'evenement qu'ecoute htmx.
        // / htmx listens for input, not change.
        champ.dispatchEvent(new Event("input", { bubbles: true }));
      });
      groupe.appendChild(texte);

      // La boite est gonflee d'une marge : deux sommets voisins d'un meme
      // massif donnaient deux noms colles, qui se lisent comme du bruit. Une
      // etiquette qui chevauche est RETIREE, jamais deplacee : poussee
      // ailleurs, elle ne designerait plus son sommet.
      // / Overlapping labels are dropped, never moved: a moved label points at
      //   the wrong peak.
      const brut = texte.getBBox();
      const marge = 26 * parPixel;
      const boite = {
        x: brut.x - marge, y: brut.y - marge,
        largeur: brut.width + 2 * marge, hauteur: brut.height + 2 * marge,
      };
      const chevauche = posees.some((autre) =>
        !(boite.x + boite.largeur < autre.x || autre.x + autre.largeur < boite.x ||
          boite.y + boite.hauteur < autre.y || autre.y + autre.hauteur < boite.y));
      if (chevauche) texte.remove();
      else posees.push(boite);
    }
  }
```

Le halo de papier de `.etiquette` (`paint-order: stroke`, contour de la couleur du papier) vient du CSS de la tâche 7 : **il est obligatoire, pas décoratif** — c'est lui qui tient le contraste d'un tag machine en encre ténue posé sur les courbes claires.

- [ ] **Étape 4 : vérifier à l'œil**

`make start`, ouvrir `/`.
Attendu : huit massifs, des noms posés sur les sommets, aucune étiquette qui en chevauche une autre, rien en console.

- [ ] **Étape 5 : proposer le commit**

```
feat(ciel): relief d3-contour et étiquettes de région
```

---

## Tâche 9 : les étoiles, les couleurs et la recherche

**Fichiers :**
- Modifier : `capsules/static/capsules/ciel.js`

**Interfaces :**
- Consomme : `donnees-etoiles` (tâche 7), le relief (tâche 8).
- Produit : `choisir(uuid, origine)`, `recolorer()`, le sélecteur `#choix-couleur`.

- [ ] **Étape 1 : dessiner les étoiles et les colorer**

```javascript
  const TEINTES_VOIX = { 1: 78, 2: 38, 3: 12 };   // ambre, terracotta, rose
  const pastilles = new Map();
  let encodage = localStorage.getItem("ciel:couleur") || "duree";
  let choisie = null;

  function teinte(clameur) {
    if (encodage === "voix") {
      return TEINTES_VOIX[Math.min(3, Math.max(1, clameur.voix || 1))];
    }
    if (encodage === "heure") {
      return clameur.heure >= 7 && clameur.heure < 20 ? 80 : 5;
    }
    // Duree : l'arc chaud, de la breve au dore, borne a trois minutes — au
    // dela, l'ecart ne se voit plus. / Capped at three minutes.
    return Math.round(350 + Math.min(1, (clameur.duree || 0) / 180) * 110) % 360;
  }

  function clarte(rang) {
    /*
     * LA FRAICHEUR SE LIT EN CLARTE, JAMAIS EN TEINTE : deux informations sur
     * la meme dimension n'en donnent aucune. Le serveur envoie les etoiles de
     * la plus recente a la plus ancienne, donc le rang suffit — pas une date a
     * relire. / Freshness is lightness; the server sends newest first.
     */
    const part = CORPUS.length > 1 ? rang / (CORPUS.length - 1) : 0;
    return 0.86 - part * 0.26;
  }

  const couleur = (clameur, rang) =>
    `oklch(${clarte(rang).toFixed(3)} 0.13 ${teinte(clameur)})`;

  function dessinerLesEtoiles() {
    const groupe = document.getElementById("etoiles");
    const fragment = document.createDocumentFragment();

    CORPUS.forEach((clameur, rang) => {
      const etoile = document.createElementNS(ESPACE, "circle");
      etoile.setAttribute("cx", (clameur.x * COTE).toFixed(1));
      etoile.setAttribute("cy", (clameur.y * COTE).toFixed(1));
      // Une clameur plus ecoutee brille plus fort ; la racine carree evite
      // qu'une seule tres ecoutee ecrase tout le ciel.
      // / Square root: one popular capsule must not swallow the sky.
      etoile.setAttribute(
        "r", (6 + Math.min(10, Math.sqrt(clameur.ecoutes || 0) * 2.2)).toFixed(1)
      );
      etoile.setAttribute("fill", couleur(clameur, rang));
      etoile.setAttribute("opacity", "0.85");
      etoile.setAttribute("class", "etoile");
      etoile.setAttribute("tabindex", "0");
      etoile.setAttribute("role", "button");
      etoile.setAttribute("aria-label", clameur.titre);
      etoile.addEventListener("keydown", (evenement) => {
        if (evenement.key === "Enter" || evenement.key === " ") {
          evenement.preventDefault();
          choisir(clameur.uuid, "ciel");
        }
      });
      pastilles.set(clameur.uuid, etoile);
      fragment.appendChild(etoile);
    });
    groupe.appendChild(fragment);
  }

  function recolorer() {
    CORPUS.forEach((clameur, rang) => {
      const teinteCourante = couleur(clameur, rang);
      pastilles.get(clameur.uuid).setAttribute("fill", teinteCourante);
      // La pastille de la fiche porte la meme couleur que son etoile : c'est
      // ce qui relie les deux ecrans quand on passe de l'un a l'autre.
      // / The card's dot matches its star: that is what ties the two screens.
      const fiche = document.getElementById(`clameur-${clameur.uuid}`);
      if (fiche) fiche.style.setProperty("--astre", teinteCourante);
    });
    document.getElementById("legende").textContent = LEGENDES[`legende${
      encodage.charAt(0).toUpperCase() + encodage.slice(1)
    }`];
  }

  // Les trois phrases viennent du gabarit, pas du JavaScript : le projet est
  // traduit, et une chaine ecrite ici echapperait a `makemessages`.
  // / The three sentences come from the template: JS strings escape gettext.
  const LEGENDES = document.getElementById("choix-couleur").dataset;

  document.getElementById("choix-couleur").addEventListener("click", (evenement) => {
    const bouton = evenement.target.closest("button[data-encodage]");
    if (!bouton) return;
    encodage = bouton.dataset.encodage;
    try {
      localStorage.setItem("ciel:couleur", encodage);
    } catch (erreur) {
      // Navigation privee, stockage refuse : le choix vaut pour la visite.
      // / Private browsing: the choice lasts for this visit only.
    }
    for (const autre of evenement.currentTarget.querySelectorAll("button")) {
      autre.setAttribute("aria-pressed", String(autre === bouton));
    }
    recolorer();
  });
```

- [ ] **Étape 2 : le toucher au plus proche**

```javascript
  // UN APPUI N'IMPORTE OU CHOISIT L'ETOILE LA PLUS PROCHE. Une etoile fait
  // deux a quatre pixels sur un telephone, un doigt en demande quarante-quatre :
  // sans ce rayon, le ciel n'est touchable par personne.
  // / A finger needs 44 px and a star is 3: without this radius, nothing is
  //   tappable on a phone.
  const RAYON_DU_DOIGT = 30;

  svg.addEventListener("click", (evenement) => {
    /*
     * LA CONVERSION PASSE PAR LA MATRICE DU SVG. Calculer a la main depuis le
     * cadre suppose que le dessin remplit exactement le panneau : sous
     * `preserveAspectRatio` a `meet`, il est centre avec des bandes vides, et
     * les deux axes n'ont meme pas la meme echelle si on les calcule ainsi —
     * le point clique se retrouve decale, d'autant plus que le panneau est loin
     * du carre. / getScreenCTM knows about the letterboxing; we do not.
     */
    const matrice = svg.getScreenCTM();
    if (!matrice) return;
    const point = new DOMPoint(evenement.clientX, evenement.clientY)
      .matrixTransform(matrice.inverse());
    const x = point.x;
    const y = point.y;
    const parPixel = 1 / matrice.a;

    let trouvee = null;
    let distance = Infinity;
    for (const clameur of CORPUS) {
      const ecart = Math.hypot(clameur.x * COTE - x, clameur.y * COTE - y);
      if (ecart < distance) { distance = ecart; trouvee = clameur; }
    }
    // Au-dela du rayon, on ne choisit rien : un appui dans le vide ne doit pas
    // faire sauter la liste a l'autre bout du corpus.
    // / Beyond the radius, nothing: a tap in the void must not jump the list.
    if (trouvee && distance <= RAYON_DU_DOIGT * parPixel) choisir(trouvee.uuid, "ciel");
  });
```

- [ ] **Étape 3 : brancher la recherche**

```javascript
  // HTMX REMPLACE #resultats A CHAQUE FRAPPE : les etoiles ne peuvent pas
  // vivre dans ce DOM-la. Elles viennent du json_script, et l'on relit
  // seulement QUI est reste dans la liste pour palir les autres.
  // / Stars come from json_script; we only re-read which cards survived.
  document.body.addEventListener("htmx:afterSwap", (evenement) => {
    if (evenement.target.id !== "resultats") return;

    const presents = new Set(
      [...document.querySelectorAll("#resultats .clameur")].map((f) => f.dataset.uuid)
    );
    // Une recherche sans resultat laisse le paysage entier et TOUTES les
    // etoiles pales : c'est la reponse juste a « rien ne correspond ».
    // / An empty search pales every star and keeps the whole landscape.
    for (const [uuid, etoile] of pastilles) {
      etoile.classList.toggle("pale", !presents.has(uuid));
    }

    // LES FICHES REVIENNENT NEUVES DU SERVEUR : teinte de la duree, et aucune
    // selection. Sans ces deux lignes, changer l'encodage puis taper une
    // lettre ramenerait toutes les pastilles a la couleur d'origine, et la
    // clameur en cours perdrait sa marque.
    // / Swapped cards come back server-fresh: recolour and re-mark them.
    recolorer();
    if (choisie) {
      document.getElementById(`clameur-${choisie}`)?.setAttribute("aria-current", "true");
    }
  });
```
Le relief et les étiquettes **ne bougent pas** : ils décrivent le corpus. L'opacité des étoiles pâlies ne descend pas sous 0,35.

- [ ] **Étape 4 : la sélection, le défilement et les écoutes**

```javascript
  // LE CONTENEUR QUI DEFILE, ET NON CE QUE HTMX REMPLACE. `#resultats` est
  // remplace a chaque frappe : son parent immediat change avec lui.
  // / The scrolling container, not the swapped fragment.
  const panneauListe = document.getElementById("panneau-liste");
  const surMobile = () => window.matchMedia("(max-width: 800px)").matches;

  // Declare ICI bien qu'il ne serve qu'a la derive (tache 11) : l'ecouteur
  // `play` ci-dessous le compare pour ne pas s'arreter lui-meme.
  // / Declared here though the drift uses it: the play listener compares to it.
  const lecteurDeLaDerive = new Audio();

  function choisir(uuid, origine) {
    if (choisie && choisie !== uuid) {
      document.getElementById(`clameur-${choisie}`)?.setAttribute("aria-current", "false");
      const ancienne = pastilles.get(choisie);
      if (ancienne) {
        ancienne.classList.remove("choisie");
        ancienne.setAttribute("opacity", "0.85");
      }
    }
    choisie = uuid;

    const fiche = document.getElementById(`clameur-${uuid}`);
    fiche?.setAttribute("aria-current", "true");
    const etoile = pastilles.get(uuid);
    if (etoile) {
      etoile.classList.add("choisie");
      etoile.setAttribute("opacity", "1");
    }

    // On ne defile que si le geste vient du ciel : venant de la liste,
    // l'element est deja sous les yeux et le deplacer le ferait fuir.
    // / Only scroll when the gesture came from the sky.
    if (origine === "ciel" && fiche) {
      if (surMobile()) {
        window.scrollTo({
          top: fiche.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.45,
          behavior: "smooth",
        });
      } else {
        panneauListe.scrollTo({
          top: fiche.offsetTop - panneauListe.clientHeight / 2 + fiche.offsetHeight / 2,
          behavior: "smooth",
        });
      }
    }
    cadrer();
  }

  // L'evenement `play` ne remonte pas : on ecoute en phase de capture, sur un
  // parent que HTMX ne remplace jamais.
  // / `play` does not bubble: capture, on a parent HTMX never swaps.
  document.body.addEventListener("play", (evenement) => {
    const lecteur = evenement.target;
    if (!lecteur.matches || !lecteur.matches("audio")) return;

    // Un seul son a la fois : cent lecteurs qui se chevauchent seraient
    // inecoutables. / One sound at a time.
    for (const autre of document.querySelectorAll("audio")) {
      if (autre !== lecteur && !autre.paused) autre.pause();
    }
    if (lecteur !== lecteurDeLaDerive) arreterLaDerive();

    const uuid = lecteur.dataset.uuid;
    if (uuid) {
      choisir(uuid, "liste");
      compterUneEcoute(uuid);
    }
  }, true);

  const dejaComptees = new Set();

  function compterUneEcoute(uuid) {
    if (dejaComptees.has(uuid)) return;   // une ecoute par page, pas par pause
    dejaComptees.add(uuid);
    fetch(window.URL_ECOUTE.replace("00000000-0000-0000-0000-000000000000", uuid), {
      method: "POST",
      headers: { "X-CSRFToken": window.JETON_CSRF },
    }).catch(() => {});
  }
```

`window.URL_ECOUTE` et `window.JETON_CSRF` sont posés par le gabarit (tâche 7), exactement comme le faisait l'ancien `constellation.html`.

- [ ] **Étape 5 : écrire l'amorçage**

Sans lui, rien ne se dessine : les fonctions existent et personne ne les appelle. À placer **en dernier** dans `ciel.js`, avant la fermeture de la fonction anonyme.

```javascript
  // Deux fonctions des taches suivantes sont appelees ici : `cadrer` (tache 10)
  // et `arreterLaDerive` (tache 11). Tant qu'elles n'existent pas, poser ces
  // deux coquilles vides et les SUPPRIMER en arrivant a leur tache — sans
  // elles, le premier clic leve une ReferenceError.
  // / Two stubs until tasks 10 and 11 replace them.
  function cadrer() {}
  function arreterLaDerive() {}

  dessinerLeRelief();
  dessinerLesEtoiles();
  recolorer();
  poserLesEtiquettes();

  // Le bouton actif doit refleter le choix retenu en memoire, sinon la page
  // colore par la duree tout en montrant « Voix » enfonce.
  // / The pressed button must match the remembered choice.
  for (const bouton of document.querySelectorAll("#choix-couleur button")) {
    bouton.setAttribute("aria-pressed", String(bouton.dataset.encodage === encodage));
  }
```

- [ ] **Étape 6 : vérifier à l'œil**

Attendu : un appui dans le vide attrape l'étoile la plus proche ; le sélecteur recolore étoiles et pastilles ; taper dans la recherche pâlit les étoiles hors résultat sans toucher au relief ; lancer une lecture illumine la bonne étoile ; recharger la page garde l'encodage choisi.

- [ ] **Étape 7 : proposer le commit**

```
feat(ciel): étoiles, encodages de couleur et lien avec la recherche
```

---

## Tâche 10 : le bandeau mobile

**Fichiers :**
- Modifier : `capsules/static/capsules/ciel.js`, `capsules/templates/capsules/liste.html` (CSS)

- [ ] **Étape 1 : les deux états et le cadrage**

```javascript
  const panneauCiel = document.querySelector(".panneau-ciel");

  // DEUX ETATS, PAS UNE HAUTEUR CONTINUE. Une hauteur pilotee au pixel pres
  // demande un calcul par image et rejoue le placement des etiquettes a chaque
  // fois ; l'oeil, lui, ne distingue que « deploye » et « bandeau ».
  // / Two states: a per-pixel height would re-run label layout every frame.
  // DEUX SEUILS, ET NON UN SEUL : replier a 260 px et deployer a 200 px. Avec
  // un seuil unique, le changement de hauteur deplace la page, ce qui repasse
  // le seuil, et le bandeau bat entre ses deux etats.
  // / Hysteresis: one threshold makes the band oscillate, since resizing it
  //   moves the page back across that very threshold.
  const SEUIL_DU_REPLI = 260;
  const SEUIL_DU_DEPLOIEMENT = 200;
  const FENETRE_REPLIEE = 420;

  let replie = false;
  let enAttente = false;

  window.addEventListener("scroll", () => {
    if (!surMobile() || enAttente) return;
    enAttente = true;
    requestAnimationFrame(() => {
      enAttente = false;
      const doitReplier = replie
        ? window.scrollY > SEUIL_DU_DEPLOIEMENT
        : window.scrollY > SEUIL_DU_REPLI;
      if (doitReplier === replie) return;
      replie = doitReplier;
      panneauCiel.classList.toggle("replie", replie);
      cadrer();
    });
  }, { passive: true });

  function cadrer() {
    if (!surMobile() || !replie) {
      svg.setAttribute("viewBox", `0 0 ${COTE} ${COTE}`);
    } else {
      /*
       * REPLIE, ON NE MONTRE PAS UN CIEL MINUSCULE : on cadre la zone autour
       * de l'etoile en cours. Un bandeau de cent trente pixels de haut rendrait
       * le ciel entier illisible, alors qu'une fenetre serree reste un paysage.
       * / Collapsed, we frame the current star rather than shrink everything.
       */
      const centre = CORPUS.find((c) => c.uuid === choisie) || { x: 0.5, y: 0.5 };
      // LA FENETRE PREND LE RATIO DU BANDEAU. Un viewBox carre dans un bandeau
      // large et court serait ramene a un carre de la hauteur du bandeau,
      // centre au milieu : on aurait retreci le ciel au lieu de le cadrer.
      // / A square viewBox in a wide, short band shrinks the sky instead of
      //   framing it.
      const cadre = svg.getBoundingClientRect();
      const largeur = FENETRE_REPLIEE;
      const hauteur = cadre.width ? largeur * (cadre.height / cadre.width) : largeur;
      const borne = (valeur, taille) => Math.max(0, Math.min(COTE - taille, valeur));
      const x = borne(centre.x * COTE - largeur / 2, largeur);
      const y = borne(centre.y * COTE - hauteur / 2, hauteur);
      svg.setAttribute(
        "viewBox", `${x.toFixed(0)} ${y.toFixed(0)} ${largeur.toFixed(0)} ${hauteur.toFixed(0)}`
      );
    }
    // L'echelle a change, donc la taille visee des etiquettes aussi.
    // / The scale changed, so the labels' target size did too.
    poserLesEtiquettes();
  }

  // Le bandeau replie ramene en haut de page, ou le ciel est entier.
  // / The collapsed band takes you back to the full sky.
  panneauCiel.addEventListener("dblclick", () => {
    if (surMobile()) window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("resize", cadrer);
```

- [ ] **Étape 2 : le CSS des deux états**

Dans `liste.html`, sous 800 px : `.panneau-ciel { position: sticky; top: 0; height: 50dvh; transition: height var(--dur-moyen) var(--ease-out); }` et `.panneau-ciel.replie { height: 22dvh; }`. Sous `prefers-reduced-motion`, la transition disparaît — les deux états restent.

- [ ] **Étape 3 : vérifier sur un vrai téléphone**

Ouvrir le site local depuis un téléphone du même réseau (ou l'artefact de la maquette pour comparer).
Attendu : le ciel occupe la moitié de l'écran au chargement, se replie en bandeau au défilement, et le bandeau suit l'étoile en cours. Les noms de région restent lisibles et touchables.

- [ ] **Étape 4 : proposer le commit**

```
feat(ciel): bandeau mobile à deux états, cadré sur l'étoile choisie
```

---

## Tâche 11 : la dérive

**Fichiers :**
- Modifier : `capsules/static/capsules/ciel.js`, `capsules/templates/capsules/liste.html` (bouton)

- [ ] **Étape 1 : un seul élément audio**

```javascript
  // UN SEUL LECTEUR POUR TOUTE LA DERIVE. Sur iOS, `play()` sur un autre
  // element que celui qu'un doigt a touche est refuse : en changeant la source
  // d'un lecteur deja debloque par l'appui initial, l'enchainement passe.
  // / iOS refuses play() on an element no gesture has unlocked.
  const lecteurDeLaDerive = new Audio();   // DEJA DECLARE A LA TACHE 9
```
Le bouton « Laisser dériver » débloque ce lecteur (premier `play()` dans le geste), puis chaque étape change `src` et rappelle `play()`. L'événement `ended` enchaîne. **`lecteurDeLaDerive` est déclaré à la tâche 9** : ne pas le déclarer deux fois — cette ligne est rappelée ici pour la lecture seule.

- [ ] **Étape 2 : le choix de la suivante, le trait et les arrêts**

```javascript
  const bouton = document.getElementById("deriver");
  const annonce = document.getElementById("annonce-derive");   // aria-live="polite"
  const entendues = new Set();
  let deriveActive = false;
  let trace = null;
  let points = [];

  function fichesDeLaListe() {
    /*
     * SEULEMENT CE QUI EST DANS LA LISTE : c'est la que vivent l'URL de
     * l'audio et la cible du defilement. Une recherche filtree devient donc
     * une derive thematique, ce qui est un usage et non un defaut.
     * / Only what the list holds: a filtered search becomes a themed drift.
     */
    const presentes = new Map();
    for (const fiche of document.querySelectorAll("#resultats .clameur")) {
      presentes.set(fiche.dataset.uuid, fiche);
    }
    return presentes;
  }

  function laPlusProche(depuis, presentes) {
    let trouvee = null;
    let distance = Infinity;
    for (const clameur of CORPUS) {
      if (entendues.has(clameur.uuid) || !presentes.has(clameur.uuid)) continue;
      const ecart = Math.hypot(clameur.x - depuis.x, clameur.y - depuis.y);
      if (ecart < distance) { distance = ecart; trouvee = clameur; }
    }
    return trouvee;
  }

  function jouer(clameur, presentes) {
    const source = presentes.get(clameur.uuid)?.querySelector("audio source");
    if (!source || !source.src) { arreterLaDerive(); return; }

    entendues.add(clameur.uuid);
    lecteurDeLaDerive.src = source.src;
    lecteurDeLaDerive.play().catch(() => arreterLaDerive());

    choisir(clameur.uuid, "ciel");
    compterUneEcoute(clameur.uuid);
    annonce.textContent = clameur.titre;

    points.push(`${(clameur.x * COTE).toFixed(0)},${(clameur.y * COTE).toFixed(0)}`);
    trace.setAttribute("points", points.join(" "));
  }

  function arreterLaDerive() {
    if (!deriveActive) return;
    deriveActive = false;
    lecteurDeLaDerive.pause();
    bouton.textContent = bouton.dataset.depart;
    bouton.setAttribute("aria-pressed", "false");
    trace?.remove();
    trace = null;
    points = [];
  }

  bouton.addEventListener("click", () => {
    if (deriveActive) { arreterLaDerive(); return; }

    const presentes = fichesDeLaListe();
    const depart = CORPUS.find((c) => c.uuid === choisie && presentes.has(c.uuid))
                || CORPUS.find((c) => presentes.has(c.uuid));
    if (!depart) return;

    deriveActive = true;
    entendues.clear();
    bouton.textContent = bouton.dataset.arret;
    bouton.setAttribute("aria-pressed", "true");
    trace = document.createElementNS(ESPACE, "polyline");
    trace.setAttribute("class", "trace");
    document.getElementById("traces").appendChild(trace);
    points = [];

    jouer(depart, presentes);
  });

  lecteurDeLaDerive.addEventListener("ended", () => {
    if (!deriveActive) return;
    const presentes = fichesDeLaListe();
    const courante = CORPUS.find((c) => c.uuid === choisie);
    const prochaine = courante && laPlusProche(courante, presentes);
    if (!prochaine) { arreterLaDerive(); return; }
    jouer(prochaine, presentes);
  });

  // Toucher une autre etoile arrete la derive : jamais de son qui continue
  // tout seul apres un geste contraire.
  // / Tapping another star stops the drift: no sound outlives a contrary gesture.
  svg.addEventListener("click", () => {
    if (deriveActive && !lecteurDeLaDerive.paused) arreterLaDerive();
  }, true);
```

Le bouton porte `data-depart` et `data-arret` (les deux libellés traduits), et `#annonce-derive` est un `<p class="sr-only" aria-live="polite">` : c'est ce qui dit le titre en cours à qui n'a pas l'écran. La `polyline` `.trace` n'anime rien sous `prefers-reduced-motion` — elle se contente d'exister.

- [ ] **Étape 4 : vérifier en vrai, bureau puis iPhone**

Attendu, sur téléphone : l'enchaînement se poursuit sans nouveau geste. **Si iOS refuse malgré le lecteur unique, s'arrêter et le signaler au mainteneur** plutôt que d'empiler les contournements.

- [ ] **Étape 5 : proposer le commit**

```
feat(ciel): la dérive, de proche en proche
```

---

## Tâche 12 : les fixtures, la documentation et la vérification finale

**Fichiers :**
- Modifier : `capsules/management/commands/creer_des_clameurs.py`
- Modifier : `README.md`, `docs/PASSATION-PRODUCTION.md`, `Makefile` (texte d'aide)

- [ ] **Étape 1 : de vrais tags machine dans les fixtures**

`creer_des_clameurs --avec-mistral` appelle déjà l'API pour les vecteurs et six voix. Y ajouter, pour un quart du corpus, un appel à `taguer` — donc de **vrais** tags machine. Sans clé, le repli hors ligne pose des tags machine synthétiques, distincts de ceux de l'auteur. Sans cela, le repli en italique n'est exercé ni par les tests ni à l'œil.

- [ ] **Étape 2 : mettre la documentation à jour**

- `README.md` : la section « Le ciel, en sommeil » devient « Le ciel » ; dire que `/` est le double écran, que le recalcul est automatique, et que `make constellation` reste là pour forcer un calcul.
- `docs/PASSATION-PRODUCTION.md` : remplacer « Le ciel est en sommeil » par la manœuvre de déploiement — **`make constellation` fait partie du déploiement**, puisque rien ne déclenche de calcul tant qu'aucune clameur n'est déposée, et que la production n'a plus de vecteurs frais depuis le 02/09.
- `Makefile` : l'aide de la cible `constellation` perd la mention « en sommeil » et dit ce qu'elle fait vraiment — **elle recalcule le relief et les régions ; elle ne redéplace les étoiles que si l'une d'elles attend encore sa position.**

- [ ] **Étape 3 : la suite complète, puis le corpus réel**

```bash
make test
docker compose run --rm web python manage.py creer_des_clameurs --nombre 100 --vider --avec-mistral
docker compose run --rm web python manage.py projeter_la_constellation
make start
```

- [ ] **Étape 4 : la liste de vérification manuelle à remettre au mainteneur**

1. `/` montre la liste et le ciel ; le relief a plusieurs massifs et des noms.
2. Une recherche pâlit les étoiles sans toucher au relief ; la vider les rallume.
3. Un appui dans le vide attrape l'étoile la plus proche ; la fiche défile et s'illumine.
4. Le sélecteur de couleur change étoiles et pastilles, et le choix survit à un rechargement.
5. « Laisser dériver » enchaîne les clameurs, trace le chemin, et s'arrête au premier geste contraire.
6. Sur téléphone : le ciel se replie en bandeau, qui suit l'étoile en cours ; les noms restent touchables.
7. Déposer une vraie clameur : elle apparaît **immédiatement** dans la liste avec une pastille creuse, et reçoit son étoile en deux minutes environ.
8. Retirer une clameur : son étoile disparaît au recalcul suivant.

- [ ] **Étape 5 : proposer le commit**

```
feat(ciel): fixtures avec tags machine, documentation à jour
```
