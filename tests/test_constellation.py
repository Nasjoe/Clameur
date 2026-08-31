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

    La borne vient du corpus : la fixture `borne` en creerait une seconde avec
    le meme slug. / The borne comes from the corpus fixture.
    """
    from django.core.cache import cache

    from bornes.models import Borne

    cache.clear()
    borne = Borne.objects.filter(active=True).first()
    contenu = client.get("/").content.decode()

    assert "Enregistrer une nouvelle clameur" in contenu
    assert "<svg" in contenu, "pas de QR dans l'invitation"
    assert f"/b/{borne.slug}" in contenu


@pytest.mark.django_db
def test_sans_borne_active_aucune_invitation_n_est_proposee(client, corpus_projete):
    """Proposer d'enregistrer quand aucune borne n'ecoute serait une promesse
    en l'air. / Offering to record with no open borne would be an empty promise."""
    from django.core.cache import cache

    from bornes.models import Borne

    Borne.objects.update(active=False)
    cache.clear()

    contenu = client.get("/").content.decode()
    assert "Enregistrer une nouvelle clameur" not in contenu
