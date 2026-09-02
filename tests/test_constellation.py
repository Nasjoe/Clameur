"""Le double écran : la liste et le ciel.
/ The dual view: list and sky."""

import pytest
from django.core.management import call_command

from capsules.models import Capsule, StatutCapsule
from capsules.views import _teinte_de_la_position


@pytest.fixture
def corpus_projete(db):
    call_command("creer_des_clameurs", nombre=12, vider=True, verbosity=0)
    call_command("projeter_la_constellation", verbosity=0)
    return Capsule.objects.all()


def test_chaque_clameur_recoit_une_position_bornee(corpus_projete):
    """Hors de [0, 1], une étoile sortirait du cadre du ciel."""
    for capsule in corpus_projete:
        assert capsule.position_x is not None
        assert 0 <= capsule.position_x <= 1
        assert 0 <= capsule.position_y <= 1


def test_les_positions_ne_bougent_pas_sans_nouvelle_clameur(corpus_projete):
    """Les étoiles doivent être fixes : sinon on ne peut plus revenir à une
    clameur repérée la veille, ni la montrer à quelqu'un."""
    avant = {c.uuid: (c.position_x, c.position_y) for c in corpus_projete}
    call_command("projeter_la_constellation", verbosity=0)
    apres = {c.uuid: (c.position_x, c.position_y) for c in Capsule.objects.all()}
    assert avant == apres


def _ecart_circulaire(a: int, b: int) -> int:
    """L'écart entre deux teintes sur la roue chromatique.

    Une soustraction ordinaire est fausse ici : 350 et 45 sont voisins à l'œil,
    mais leur différence vaut 305. L'ancien test concluait au contraste sur
    cette base, et validait donc une propriété qui n'existait pas.
    / A plain subtraction is wrong: 350 and 45 look adjacent but differ by 305.
    """
    ecart = abs(a - b) % 360
    return min(ecart, 360 - ecart)


def test_deux_positions_voisines_donnent_des_teintes_voisines():
    """La couleur prolonge la carte : sans cela, un même amas virerait au
    bariolé alors que la page promet que les voisines se ressemblent."""
    assert _ecart_circulaire(
        _teinte_de_la_position(0.80, 0.50), _teinte_de_la_position(0.82, 0.52)
    ) < 15


def test_deux_amas_opposes_se_distinguent_sans_quitter_la_famille_chaude():
    """L'arc chaud ne fait que 110° : deux points diamétralement opposés sont
    donc distants d'au plus 55°, jamais complémentaires. C'est le prix assumé
    d'un ciel qui ne pose ni vert ni bleu sur un papier brun — mais la
    distinction doit rester visible.
    / The warm arc spans 110°, so opposite points differ by at most 55°."""
    ecart = _ecart_circulaire(
        _teinte_de_la_position(0.80, 0.50), _teinte_de_la_position(0.20, 0.50)
    )
    assert 35 < ecart <= 55, f"écart de {ecart}° : les amas ne se distinguent plus"


def test_la_projection_refuse_de_travailler_sur_trop_peu(db, reglages):
    """Deux points ne font pas une constellation : la commande doit le dire
    plutôt que produire une projection dégénérée.

    LES DEUX CAPSULES PORTENT UN VECTEUR, et c'est tout l'objet du test : avec
    une capsule sans embedding, `exclude(embedding=None)` l'écartait avant même
    le seuil, et supprimer le garde-fou n'aurait rien fait échouer.
    / Both capsules carry a vector: otherwise they were filtered out before the
      threshold, and removing the guard would have broken nothing.
    """
    import numpy as np

    alea = np.random.default_rng(4)
    for _ in range(2):
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
            embedding=list(alea.normal(0, 1, 1024)),
        )

    call_command("projeter_la_constellation", verbosity=0)

    assert not Capsule.objects.exclude(position_x=None).exists()


# ------------------------------------------- ce que la carte dit vraiment

def _corpus_du_regime_reel(reglages, separation=0.4, groupes=6, par_groupe=8):
    """Des vecteurs qui ressemblent à de VRAIS embeddings : des groupes nets,
    noyés dans du bruit de haute dimension.

    Mesuré le 2026-08-31 sur de vrais vecteurs `mistral-embed` : deux axes ne
    portent que 10 % de la variance, et les thèmes n'y survivent qu'à moitié.
    Les fixtures, elles, tirent huit gaussiennes bien séparées — la PCA y
    réussit toujours, et ce cas facile ne prouve donc rien.
    / Real embeddings put ~10 % of the variance on two axes; the fixtures'
      well-separated gaussians are an easy case that proves nothing.
    """
    import numpy as np

    alea = np.random.default_rng(7)
    centres = alea.normal(0, 1, (groupes, 1024))
    capsules, groupe_de = [], {}
    for numero in range(groupes):
        for _ in range(par_groupe):
            vecteur = centres[numero] * separation + alea.normal(0, 1, 1024)
            capsule = Capsule.objects.create(
                reglages=reglages,
                statut=StatutCapsule.PUBLIEE,
                duree_secondes=30,
                embedding=(vecteur / np.linalg.norm(vecteur)).tolist(),
            )
            capsules.append(capsule)
            groupe_de[capsule.uuid] = numero
    return capsules, groupe_de


def test_deux_clameurs_voisines_a_l_ecran_parlent_bien_de_la_meme_chose(reglages):
    """LA QUESTION QUE POSE LE CIEL. Une étoile voisine doit être une clameur
    voisine — sinon la carte est décorative, et le double écran ment.

    Sur ce régime, la PCA plafonnait à 79 % d'étoiles dont la plus proche
    voisine appartient au bon groupe : elle place « dans le bon quartier »
    sans placer le bon voisin.
    / The sky's whole claim: a neighbouring star must be a neighbouring clameur.
    """
    import numpy as np

    capsules, groupe_de = _corpus_du_regime_reel(reglages)
    call_command("projeter_la_constellation", verbosity=0)

    positions, groupes = [], []
    for capsule in Capsule.objects.filter(uuid__in=[c.uuid for c in capsules]):
        positions.append((capsule.position_x, capsule.position_y))
        groupes.append(groupe_de[capsule.uuid])
    positions, groupes = np.asarray(positions), np.asarray(groupes)

    distances = ((positions[:, None, :] - positions[None, :, :]) ** 2).sum(-1)
    np.fill_diagonal(distances, np.inf)
    accord = (groupes[distances.argmin(1)] == groupes).mean()

    assert accord >= 0.95, (
        f"seulement {accord:.0%} des étoiles ont pour plus proche voisine une "
        "clameur du même groupe : la carte ne dit pas grand-chose"
    )


def test_une_clameur_de_plus_ne_retourne_pas_le_ciel(reglages):
    """Le semis de départ doit garder son orientation quand le corpus grandit.

    Le signe des vecteurs singuliers rendus par `np.linalg.svd` est ARBITRAIRE :
    une clameur de plus, et une fois sur deux la PCA rend les mêmes axes à
    l'envers. Le ciel entier passe alors en miroir — et comme la teinte d'une
    étoile dérive de son angle depuis le centre, toutes changent aussi de
    couleur. C'est exactement ce que la commande promet d'empêcher : « revenir
    à une étoile repérée la veille ».
    / SVD singular vectors have an arbitrary sign: one more clameur and the sky
      flips, colours included.
    """
    import numpy as np

    from capsules.management.commands.projeter_la_constellation import Command

    commande = Command()
    alea = np.random.default_rng(0)

    retournements = 0
    for essai in range(8):
        vecteurs = alea.normal(0, 1, (40, 1024))
        vecteurs /= np.linalg.norm(vecteurs, axis=1, keepdims=True)
        une_de_plus = np.vstack([vecteurs, alea.normal(0, 1, (1, 1024))])
        une_de_plus[-1] /= np.linalg.norm(une_de_plus[-1])

        avant = commande._pca(vecteurs)
        apres = commande._pca(une_de_plus)[:-1]
        for axe in range(2):
            if np.corrcoef(avant[:, axe], apres[:, axe])[0, 1] < 0:
                retournements += 1

    assert retournements == 0, (
        f"{retournements} axes sur 16 ont changé de signe : le ciel est mis en "
        "miroir quand une clameur s'ajoute"
    )


@pytest.mark.django_db
def test_un_vecteur_de_norme_nulle_ne_fait_pas_tomber_la_page_d_accueil(client, reglages):
    """Un seul vecteur nul contaminait TOUTES les positions.

    La normalisation divise par la norme : à zéro, la ligne devient NaN, puis
    l'ensemble du calcul. Les NaN s'écrivent sans broncher dans un `FloatField`,
    `exclude(position_x=None)` ne les filtre pas, et la page d'accueil finit en
    500 sur `_teinte_de_la_position`. Une capsule abîmée emportait le site.
    / One zero vector turned every position into NaN and took the home page down.
    """
    import numpy as np

    alea = np.random.default_rng(1)
    for numero in range(6):
        vecteur = [0.0] * 1024 if numero == 0 else list(alea.normal(0, 1, 1024))
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE,
            duree_secondes=30, embedding=vecteur,
        )

    call_command("projeter_la_constellation", verbosity=0)

    positions = [
        (c.position_x, c.position_y)
        for c in Capsule.objects.exclude(position_x=None)
    ]
    assert positions, "aucune clameur n'a été projetée"
    for x, y in positions:
        assert np.isfinite(x) and np.isfinite(y), "une position NaN est entrée en base"

    assert client.get("/").status_code == 200


def test_la_fidelite_ne_flatte_pas_un_corpus_minuscule():
    """Sur six clameurs, « l'une des cinq plus proches » les désigne toutes.

    La mesure annonçait donc 100 % sur un ciel jeté au hasard, et son
    avertissement ne pouvait jamais partir — précisément en début
    d'événement, quand l'opérateur a le plus besoin de savoir si le ciel dit
    quelque chose. / On six clameurs, "one of the five nearest" means "any of
    them": the measure reported 100 % on a random sky.
    """
    import numpy as np

    from capsules.management.commands.projeter_la_constellation import Command

    commande = Command()
    alea = np.random.default_rng(2)
    vecteurs = alea.normal(0, 1, (6, 1024))
    vecteurs /= np.linalg.norm(vecteurs, axis=1, keepdims=True)

    au_hasard = [
        commande._fidelite(vecteurs, alea.random((6, 2))) for _ in range(20)
    ]
    assert np.mean(au_hasard) < 0.8, (
        f"un ciel jeté au hasard obtient {np.mean(au_hasard):.0%} de fidélité : "
        "la mesure ne mesure rien à cette taille"
    )
