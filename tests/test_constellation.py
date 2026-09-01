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


def test_la_page_rend_les_fiches_cote_serveur(client, corpus_projete):
    """La liste est rendue par Django, et non construite en JavaScript : c'est
    la condition pour que HTMX puisse y remplacer une transcription par swap
    OOB quand elle arrive.
    / Server-rendered so HTMX has something to OOB-swap into."""
    reponse = client.get("/")
    assert reponse.status_code == 200
    contenu = reponse.content.decode()

    assert contenu.count('class="clameur"') == corpus_projete.count()
    assert "lecteur-de-fiche" in contenu, "pas de lecteur audio dans les fiches"
    assert 'ws-connect="/ws/constellation"' in contenu, "pas de connexion temps réel"
    for capsule in corpus_projete:
        assert f'id="transcription-{capsule.uuid}"' in contenu


@pytest.mark.django_db
def test_une_clameur_sans_position_n_apparait_pas(client, capsule_publiee):
    """Une capsule non encore projetée n'a pas d'étoile : l'afficher en (0,0)
    créerait un amas fantôme dans un coin du ciel."""
    contenu = client.get("/").content.decode()
    assert str(capsule_publiee.uuid) not in contenu


def test_une_clameur_retiree_disparait_du_ciel(client, corpus_projete):
    retiree = corpus_projete.first()
    retiree.statut = StatutCapsule.RETIREE
    retiree.save()
    contenu = client.get("/").content.decode()
    assert str(retiree.uuid) not in contenu, "le kill switch ne vide pas le ciel"


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


def test_la_projection_refuse_de_travailler_sur_trop_peu(db, capsule_publiee):
    """Deux points ne font pas une constellation : la commande doit le dire
    plutôt que produire une projection dégénérée."""
    call_command("projeter_la_constellation", verbosity=0)
    capsule_publiee.refresh_from_db()
    assert capsule_publiee.position_x is None


def test_l_accueil_est_la_constellation(client, corpus_projete):
    """C'est la page qu'on montre a quelqu'un a qui l'on parle du projet."""
    reponse = client.get("/")
    assert reponse.status_code == 200
    assert "La constellation" in reponse.content.decode()


def test_l_invitation_porte_le_qr_de_la_borne_active(client, corpus_projete):
    """Un visiteur sur ordinateur ne peut pas enregistrer sur place : il lui
    faut son telephone, donc un QR.

    La reglages vient du corpus : la fixture `reglages` en creerait une seconde avec
    le meme slug. / The reglages comes from the corpus fixture.
    """
    from django.core.cache import cache

    from bornes.models import Reglages

    cache.clear()
    assert Reglages.objects.filter(active=True).exists()
    contenu = client.get("/").content.decode()

    assert "Enregistrer une nouvelle clameur" in contenu
    assert "<svg" in contenu, "pas de QR dans l'invitation"
    # L'invitation vise l'adresse courte, pas le slug de la reglages : c'est elle
    # qu'on encode dans le QR et qu'on dit à voix haute.
    assert "/nouvelle" in contenu


@pytest.mark.django_db
def test_lieu_ferme_aucune_invitation_n_est_proposee(client, corpus_projete):
    """Proposer d'enregistrer quand aucune reglages n'ecoute serait une promesse
    en l'air. / Offering to record with no open reglages would be an empty promise."""
    from django.core.cache import cache

    from bornes.models import Reglages

    reglages = Reglages.get_solo()
    reglages.active = False
    reglages.save()
    cache.clear()

    contenu = client.get("/").content.decode()
    assert "Enregistrer une nouvelle clameur" not in contenu


@pytest.mark.django_db
def test_l_adresse_courte_mene_a_la_page_d_enregistrement(client, corpus_projete):
    """`/nouvelle` tient dans une phrase qu'on dit à voix haute, contrairement
    à `/b/<slug>`. C'est elle qu'on encode dans le QR."""
    from django.core.cache import cache

    cache.clear()
    reponse = client.get("/nouvelle")
    assert reponse.status_code == 200
    assert "Dépose une clameur" in reponse.content.decode()

    contenu = client.get("/").content.decode()
    assert 'href="/nouvelle"' in contenu, "l'invitation doit mener à l'adresse courte"
    assert "Enregistrer avec cet appareil" in contenu


@pytest.mark.django_db
def test_lieu_ferme_l_adresse_courte_explique(client, corpus_projete):
    from django.core.cache import cache

    from bornes.models import Reglages

    reglages = Reglages.get_solo()
    reglages.active = False
    reglages.save()
    cache.clear()

    # La page reste accessible mais refuse les enregistrements : un visiteur
    # qui scanne un QR encore colle merite une explication, pas un 404.
    # / The page stays reachable and explains, rather than 404ing a live QR.
    contenu = client.get("/nouvelle").content.decode()
    assert "fermés" in contenu


@pytest.mark.django_db
def test_le_qr_porte_un_viewbox(client, corpus_projete):
    """Segno n'en émet aucun : le canevas s'étirait sans que le dessin suive,
    et le code se retrouvait tassé dans un coin de la modale.
    / Segno emits none, so the drawing stayed put while the canvas stretched."""
    from django.core.cache import cache

    cache.clear()
    contenu = client.get("/").content.decode()
    assert 'class="segno"' in contenu
    debut = contenu.index('class="segno"') - 400
    assert "viewBox" in contenu[debut:debut + 500], "le QR ne se mettra pas à l'échelle"


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

    Sur ce régime, la PCA plafonnait à 79 % : elle place « dans le bon
    quartier » sans placer le bon voisin.
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
