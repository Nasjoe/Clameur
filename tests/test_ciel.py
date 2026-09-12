"""Les fonctions pures du ciel : projection, densité, régions.
/ The sky's pure functions: projection, density, regions.

AUCUN ACCÈS À LA BASE dans la plupart de ces tests, et c'est voulu : ce qui se
teste ici est de l'arithmétique, et elle doit pouvoir être mise en défaut sans
qu'on ait à fabriquer un corpus.
/ Mostly database-free on purpose: this is arithmetic, and it must be falsifiable
  without building a corpus first.
"""

import numpy as np
import pytest

from capsules import ciel


def test_la_densite_a_la_forme_et_l_orientation_attendues():
    """`grille[y][x]` : la première dimension est la ligne, donc y.

    Une grille transposée ne lève aucune erreur : elle rend simplement un
    relief en miroir de ses étoiles, et personne ne le voit avant l'écran.
    / A transposed grid raises nothing; it just mirrors the relief.
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
    calculée sur l'écart-type vaudrait zéro, et toute la grille serait NaN.
    / The degenerate case: a bandwidth from the standard deviation would be
      zero, and the whole grid NaN.
    """
    grille = ciel.densite(np.full((100, 2), 0.5))

    assert np.isfinite(grille).all()
    assert grille.max() > 0


# ------------------------------------------------- les sommets et les régions

def _trois_amas():
    """Trois amas nets, construits à la main.

    ON NE DEMANDE PAS CE NOMBRE À UN T-SNE : sur douze points, rien ne garantit
    le nombre de sommets qu'il produit, et le test mesurerait la projection au
    lieu de mesurer la détection.
    / Hand-built clusters: a t-SNE on twelve points guarantees no peak count.
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
    mot que personne n'a prononcé.
    / The machine always wins on score alone; the author must win outright.
    """
    positions, appartenance = _trois_amas()
    tags = []
    for numero in appartenance:
        if numero == 0:
            tags.append([("boulangerie", "machine")])
        else:
            tags.append([("nuit" if numero == 1 else "exil", "auteur")])
    for indice in (0, 1):          # deux clameurs de l'amas 0 disent « pain »
        tags[indice] = [("boulangerie", "machine"), ("pain", "auteur")]

    amas = next(
        region for region in ciel.regions(ciel.densite(positions), positions, tags)
        if region["nom"] in {"pain", "boulangerie"}
    )
    assert amas["nom"] == "pain" and amas["origine"] == "auteur"


def test_singulier_et_pluriel_comptent_ensemble():
    """« voisin » et « voisins » séparés, aucun des deux n'atteint le seuil de
    deux clameurs, et la région reste anonyme.
    / Split by plural, neither form reaches the two-clameur threshold.
    """
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

    C'est bien le seuil de RÉGION qu'on teste : un tag porté une seule fois
    serait déjà écarté par le seuil de tag, et le test ne prouverait rien.
    / The region threshold, not the tag threshold.
    """
    positions = np.array([[0.2, 0.2], [0.205, 0.205], [0.8, 0.8]])
    tags = [[("nuit", "auteur")], [("nuit", "auteur")], [("exil", "auteur")]]

    noms = {r["nom"] for r in ciel.regions(ciel.densite(positions), positions, tags)}
    assert "nuit" not in noms


@pytest.mark.django_db
def test_un_ciel_neuf_est_vide_et_ne_fait_pas_tomber_la_page(client, reglages):
    """Avant le premier calcul, le singleton existe et ne porte rien.

    L'import est LOCAL : en tête de module, un modèle manquant ferait échouer
    la collecte du fichier entier, et l'échec ne dirait plus lequel des onze
    tests il concerne.
    / Local import: a missing model would otherwise break collection for all.
    """
    from capsules.models import Ciel

    objet = Ciel.get_solo()

    assert objet.grille == []
    assert objet.regions == []
    assert objet.calcule_le is None
    assert client.get("/").status_code == 200


@pytest.mark.django_db
def test_sur_un_corpus_realiste_les_regions_restent_peu_nombreuses_et_distinctes(reglages):
    """Six groupes de huit ne doivent pas produire trente noms sur la carte.

    LE NOMBRE DE SOMMETS N'EST PAS TESTABLE : le t-SNE éclate chaque groupe en
    sous-tâches, et la détection en trouve de douze à trente selon la graine.
    Ce qui compte est ce qu'on lit à l'écran — les régions nommées.
    / Peak count is not a testable quantity here; named regions are.
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
