"""Le calcul du ciel : projection des vecteurs, puis relief et régions.
/ The sky's computation: projecting vectors, then relief and regions.

CE MODULE NE TOUCHE NI A LA BASE NI AUX REGLAGES. Il prend des tableaux et rend
des tableaux, pour que la commande, la tache Celery et les tests appellent
exactement le meme code.
/ No database here: the command, the Celery task and the tests share this code.

POURQUOI LES POSITIONS SONT STOCKEES, ET NON CALCULEES A L'AFFICHAGE.
Une projection est GLOBALE : ajouter une clameur deplace toutes les autres. Si
on la recalculait a chaque visite, la constellation serait differente a chaque
fois — on ne pourrait plus revenir a une etoile reperee la veille, ni la
montrer a quelqu'un. Les etoiles doivent etre fixes entre deux recalculs.
/ A projection is global: recomputing it per visit would move every star.

POURQUOI T-SNE, ET POURQUOI ECRIT ICI.
La PCA a tenu tant que les vecteurs venaient des fixtures — huit gaussiennes
bien separees, un cas facile. Sur de VRAIS vecteurs `mistral-embed`, elle place
« dans le bon quartier » sans placer le bon voisin.

Mesure du 2026-08-31, sur soixante clameurs variees. Une seule question :
pour chaque clameur, ou se situe sa voisine D'ECRAN dans son vrai classement
semantique ?

    PCA     rang median 8 sur 59, et le bon voisin affiche 1 fois sur 3
    t-SNE   rang median 0,        et le bon voisin affiche 9 fois sur 10

`fidelite` mesure la meme chose plus grossierement, mais a chaque passage :
la part des etoiles dont la voisine d'ecran fait partie de leurs plus proches
par le sens. Sur le corpus de demonstration enrichi pour de vrai, elle passe
d'environ 77 % avec la PCA a 99 % avec t-SNE.

scikit-learn apporterait cela en une ligne, et une centaine de megaoctets dans
l'image pour une commande lancee de loin en loin. Le calcul ci-dessous fait le
meme travail avec le numpy deja installe.
/ PCA held only while the vectors came from well-separated fixtures; on real
  embeddings it puts a clameur in the right neighbourhood but next to the wrong
  neighbour. Avoiding scikit-learn saves 100 MB for an occasional command.

POURQUOI L'INITIALISATION PAR LA PCA.
Un t-SNE parti d'un nuage aleatoire donne un ciel different a chaque passage :
l'orientation change, et l'on ne retrouve plus une etoile reperee la veille.
Parti de la PCA, il rend les MEMES POSITIONS pour les memes vecteurs, et il
garde l'orientation d'ensemble d'une projection a l'autre — a condition de
fixer le signe des axes, que `svd` choisit sinon au hasard (voir `pca`). La
promesse vaut a bibliotheques constantes : une autre version de BLAS peut
rendre une decomposition legerement differente.
/ The PCA start gives identical positions for identical vectors and keeps the
  overall orientation, provided the axis signs are pinned down (see pca).

POURQUOI LA VARIANCE EXPLIQUEE N'EST PAS AFFICHEE.
Elle passait pour le signal d'alerte. Elle ment : mesuree a 18,5 % sur les
fixtures — ou la separation est parfaite — et a 9,7 % sur de vraies clameurs.
Elle MONTE quand le probleme devient facile pour de mauvaises raisons. Ce qui
compte est la part des etoiles dont la plus proche voisine a l'ecran fait
vraiment partie de ses plus proches par le sens.
/ Explained variance was the alert signal, and it lies: 18.5 % on the easy
  fixtures against 9.7 % on real clameurs. We show neighbourhood quality.

LA PROJECTION EST EN O(n²). Quelques centaines de clameurs passent en secondes ;
au-dela de quelques milliers, il faudra une autre methode.
/ O(n²): fine for hundreds, not for thousands.
"""

import unicodedata

import numpy as np

MARGE = 0.04

# Combien de voisines chaque clameur « connait ». Trop peu, le ciel se casse en
# miettes ; trop, les groupes fondent les uns dans les autres.
# / How many neighbours each clameur knows: too few shatters the sky, too many
#   melts the groups together.
VOISINES = 30
ITERATIONS = 800

# Le relief se calcule sur une grille de ce cote. Quatre-vingt-seize cases
# suffisent a six cents clameurs, et la grille tient en quarante kilo-octets
# dans la page. / Ninety-six cells is enough for six hundred clameurs.
CASES = 96

# EN CASES, ET NON PAR LA REGLE DE SILVERMAN. Apres la mise a l'echelle par
# axe, l'ecart-type des positions vaut toujours environ un quart : Silverman ne
# mesurerait plus rien, et sa largeur retrecirait avec la taille du corpus — le
# relief changerait de nature en grandissant.
# / A constant in cells: after per-axis rescaling, Silverman measures nothing.
LARGEUR_NOYAU = 3.5

# Une region de moins de trois clameurs n'est pas nommee : c'est ce seuil, et
# lui seul, qui ecarte le bruit. Un tag porte par une seule clameur ne nomme
# rien non plus. / These two thresholds are what keeps noise off the map.
MIN_PAR_REGION = 3
MIN_PAR_TAG = 2


def projeter(vecteurs: np.ndarray) -> np.ndarray:
    """t-SNE initialise par une PCA, puis mise a l'echelle dans [0, 1].
    / PCA-seeded t-SNE, then rescaled into [0, 1]."""
    depart = pca(vecteurs)
    plan = tsne(vecteurs, depart)

    # Mise a l'echelle par axe : sans elle, un nuage tres allonge sur un
    # axe se tasserait en une ligne a l'ecran.
    # / Per-axis rescaling: otherwise an elongated cloud collapses to a line.
    minimum, maximum = plan.min(axis=0), plan.max(axis=0)
    etendue = np.where(maximum - minimum == 0, 1.0, maximum - minimum)
    return MARGE + (plan - minimum) / etendue * (1 - 2 * MARGE)


def pca(vecteurs: np.ndarray) -> np.ndarray:
    """Les deux axes de plus grande variance. / The two widest axes."""
    centres = vecteurs - vecteurs.mean(axis=0)
    _u, _valeurs, directions = np.linalg.svd(centres, full_matrices=False)

    # LE SIGNE DES AXES EST ARBITRAIRE, ET IL FAUT LE FIXER SOI-MEME.
    # `svd` peut rendre un axe ou son oppose, indifferemment. Une clameur
    # de plus, et une fois sur deux les memes axes revenaient a l'envers :
    # le ciel entier passait en miroir, et comme la teinte d'une etoile
    # derivait de son angle depuis le centre, toutes changeaient aussi de
    # couleur. On impose donc une convention — la composante de plus grand
    # module est positive — et l'orientation tient d'une projection a
    # l'autre. / SVD signs are arbitrary; without a convention the whole
    # sky mirrors itself when one clameur is added.
    axes = directions[:2]
    dominantes = np.abs(axes).argmax(axis=1)
    signes = np.sign(axes[np.arange(2), dominantes])
    axes = axes * np.where(signes == 0, 1.0, signes)[:, None]
    return centres @ axes.T


def tsne(vecteurs: np.ndarray, depart: np.ndarray) -> np.ndarray:
    """t-SNE, en numpy. Rapproche a l'ecran ce qui est proche par le sens.

    Le principe tient en une phrase : on donne a chaque clameur une
    distribution de voisinage en 1024 dimensions, une autre a l'ecran, et
    l'on deplace les points jusqu'a ce que les deux se ressemblent.
    / Match the neighbourhood distributions of both spaces.
    """
    nombre = len(vecteurs)
    unitaires = vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True)

    # DISTANCES PAR PRODUIT SCALAIRE, ET NON PAR SOUSTRACTION TERME A TERME.
    # Ecrire `((u[:, None, :] - u[None, :, :]) ** 2).sum(-1)` demande un
    # tableau de n x n x 1024 flottants : trois gigaoctets pour six cents
    # clameurs, trente-trois pour deux mille. Le conteneur se fait tuer par
    # l'OOM killer, et le journal ne dit qu'un mot : « Killed ». Entre
    # vecteurs unitaires, ||a - b||² vaut 2 - 2·a·b : une multiplication de
    # matrices, et n x n en memoire.
    # / The naive form needs an n x n x 1024 array — 3 GB at six hundred
    #   capsules — and the container dies with nothing but "Killed" in the log.
    carres = np.maximum(2 - 2 * (unitaires @ unitaires.T), 0)

    voisines = max(2.0, min(float(VOISINES), (nombre - 1) / 3))
    affinites = np.zeros_like(carres)
    for indice in range(nombre):
        # Chaque clameur a son propre rayon de voisinage, trouve par
        # dichotomie : dans un amas dense il est petit, dans un coin vide
        # il est large. C'est ce qui permet aux clameurs isolees d'exister
        # quand meme. / Each point gets its own radius, so lonely clameurs
        # still find a place.
        bas, haut, cible = 1e-10, 1e10, np.log(voisines)
        for _ in range(60):
            largeur = (bas + haut) / 2
            proximites = np.exp(-carres[indice] * largeur)
            proximites[indice] = 0
            somme = proximites.sum() or 1e-12
            entropie = np.log(somme) + largeur * (carres[indice] * proximites).sum() / somme
            if entropie > cible:
                bas = largeur
            else:
                haut = largeur
        affinites[indice] = proximites / somme

    affinites = np.maximum((affinites + affinites.T) / (2 * nombre), 1e-12)

    # L'EXAGERATION PRECOCE : on gonfle les affinites au debut pour que les
    # groupes se detachent avant de se ranger. Sans elle, tout se tasse au
    # centre et rien ne se separe. / Early exaggeration: groups must pull
    # apart before they settle.
    affinites *= 4

    positions = depart / (depart.std(axis=0).mean() or 1.0) * 1e-2
    vitesse = np.zeros_like(positions)
    for iteration in range(ITERATIONS):
        if iteration == 100:
            affinites /= 4
        ecarts = positions[:, None, :] - positions[None, :, :]
        inverses = 1 / (1 + (ecarts**2).sum(-1))
        np.fill_diagonal(inverses, 0)
        projetees = np.maximum(inverses / inverses.sum(), 1e-12)
        gradient = 4 * (
            (((affinites - projetees) * inverses)[:, :, None] * ecarts).sum(1)
        )
        vitesse = (0.5 if iteration < 250 else 0.8) * vitesse - 200 * gradient
        positions = positions + vitesse
        positions -= positions.mean(axis=0)
    return positions


def fidelite(vecteurs: np.ndarray, positions: np.ndarray) -> float:
    """La part des clameurs dont la voisine d'ecran est vraiment une proche.

    C'EST LA SEULE MESURE QUI DISE QUELQUE CHOSE au sujet du ciel : il
    promet que deux etoiles cote a cote parlent de la meme chose, et c'est
    exactement ce qu'on verifie ici.
    / The only measurement that speaks to the sky's own promise.
    """
    unitaires = vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True)
    cosinus = unitaires @ unitaires.T
    np.fill_diagonal(cosinus, -np.inf)
    proches = np.argsort(-cosinus, axis=1)[:, : combien_de_proches(len(vecteurs))]

    ecrans = ((positions[:, None, :] - positions[None, :, :]) ** 2).sum(-1)
    np.fill_diagonal(ecrans, np.inf)
    voisine = ecrans.argmin(axis=1)
    return float(np.mean([voisine[i] in proches[i] for i in range(len(vecteurs))]))


def combien_de_proches(nombre: int) -> int:
    """Combien de voisines par le sens comptent comme un succes.

    JAMAIS PLUS DE LA MOITIE DU CORPUS. A cinq clameurs, « l'une des cinq
    plus proches » les designe toutes : la mesure rendait 100 % sur un ciel
    jete au hasard, et son avertissement ne pouvait jamais partir. C'est
    pourtant en debut d'evenement, sur un corpus minuscule, que l'operateur
    a le plus besoin de savoir si le ciel dit quelque chose.
    / Never more than half the corpus: at five clameurs, "one of the five
      nearest" means "any of them", and the measure flattered a random sky.
    """
    return max(1, min(5, (nombre - 1) // 2))


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
        i0, i1 = max(0, int(np.floor(cx - portee))), min(CASES - 1, int(np.ceil(cx + portee)))
        j0, j1 = max(0, int(np.floor(cy - portee))), min(CASES - 1, int(np.ceil(cy + portee)))
        if i1 < i0 or j1 < j0:
            continue
        colonnes = np.arange(i0, i1 + 1)
        lignes = np.arange(j0, j1 + 1)
        ecarts = (lignes[:, None] - cy) ** 2 + (colonnes[None, :] - cx) ** 2
        grille[j0:j1 + 1, i0:i1 + 1] += np.exp(-ecarts / (2 * LARGEUR_NOYAU**2))

    maximum = grille.max()
    return grille / maximum if maximum > 0 else grille


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


def regions(grille: np.ndarray, positions: np.ndarray, tags: list) -> list[dict]:
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

    retenues: list[dict] = []
    deja_prises: set[str] = set()
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


def _nommer(tags_des_membres: list, partout: dict, deja_prises: set) -> dict | None:
    """Le meilleur mot de la region : frequence ici, rarete ailleurs.

    C'est le TF-IDF par classe de BERTopic, que reprend WizMap.
    / Class-based TF-IDF, as in BERTopic and WizMap.
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
