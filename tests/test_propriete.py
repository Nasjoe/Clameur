"""Ce que le téléphone du visiteur se rappelle de lui.

Sans compte et sans mot de passe, la SESSION est le seul lien entre une
personne et la clameur qu'elle a déposée. Elle porte deux choses : les
clameurs qu'on a enregistrées — donc celles qu'on peut retirer — et le pseudo,
pour ne pas le retaper à chaque fois.
/ With no accounts, the session is the only link between a person and the
  clameur they recorded.
"""

import pytest
from django.urls import reverse

from capsules.models import Capsule, StatutCapsule
from tests.conftest import un_vrai_wav


@pytest.fixture
def brouillon(reglages):
    return Capsule.objects.create(
        reglages=reglages, audio_original=un_vrai_wav(), duree_secondes=12,
    )


@pytest.mark.django_db
def test_publier_retient_la_clameur_et_le_pseudo(client, brouillon):
    client.post(reverse("capsules:publier_capsule", args=[brouillon.uuid]),
                {"pseudo": "Rosa", "tags": ["marché"]})

    assert str(brouillon.uuid) in client.session["mes_clameurs"]
    assert client.session["pseudo"] == "Rosa"


@pytest.mark.django_db
def test_le_pseudo_revient_tout_seul_a_l_enregistrement_suivant(client, brouillon):
    client.post(reverse("capsules:publier_capsule", args=[brouillon.uuid]),
                {"pseudo": "Rosa"})

    page = client.get(reverse("capsules:nouvelle")).content.decode()
    assert 'value="Rosa"' in page, "le pseudo n'est pas repris"


@pytest.mark.django_db
def test_publier_sans_pseudo_n_efface_pas_celui_qu_on_connait(client, brouillon, reglages):
    """Rester anonyme une fois ne doit pas faire oublier le nom d'avant.
    / Going anonymous once must not erase the name."""
    client.post(reverse("capsules:publier_capsule", args=[brouillon.uuid]),
                {"pseudo": "Rosa"})

    autre = Capsule.objects.create(
        reglages=reglages, audio_original=un_vrai_wav(), duree_secondes=8,
    )
    client.post(reverse("capsules:publier_capsule", args=[autre.uuid]), {"pseudo": ""})

    assert client.session["pseudo"] == "Rosa"
    assert len(client.session["mes_clameurs"]) == 2


@pytest.mark.django_db
def test_la_session_dure_plusieurs_mois(settings):
    """Un ticket collé sur un mur vit plus longtemps qu'une session de deux
    semaines. Son auteur doit pouvoir le retirer des mois plus tard.
    / A ticket on a wall outlives a two-week session."""
    assert settings.SESSION_COOKIE_AGE >= 60 * 60 * 24 * 150


# ------------------------------------------------------------ le retrait

@pytest.fixture
def ma_clameur(client, brouillon):
    """Une clameur publiée depuis CETTE session : le visiteur en est l'auteur.
    / Published from this session: the visitor is its author."""
    client.post(reverse("capsules:publier_capsule", args=[brouillon.uuid]),
                {"pseudo": "Rosa"})
    brouillon.refresh_from_db()
    return brouillon


@pytest.mark.django_db
def test_l_auteur_peut_retirer_sa_clameur(client, ma_clameur):
    reponse = client.post(reverse("capsules:retirer_capsule", args=[ma_clameur.uuid]))

    ma_clameur.refresh_from_db()
    assert ma_clameur.statut == StatutCapsule.RETIREE
    assert reponse.status_code == 302


@pytest.mark.django_db
def test_un_passant_ne_peut_pas_retirer_la_clameur_d_un_autre(client, ma_clameur):
    """LE POINT SENSIBLE. Sans ce contrôle, n'importe qui ayant scanné un
    ticket pourrait faire taire son auteur.
    / Without this check, anyone who scanned a ticket could silence its author."""
    from django.test import Client

    passant = Client()
    reponse = passant.post(reverse("capsules:retirer_capsule", args=[ma_clameur.uuid]))

    ma_clameur.refresh_from_db()
    assert reponse.status_code == 403
    assert ma_clameur.statut == StatutCapsule.PUBLIEE


@pytest.mark.django_db
def test_le_staff_peut_retirer_n_importe_quelle_clameur(client, ma_clameur, django_user_model):
    """C'est le kill switch de la LCEN : l'opérateur retire sur signalement,
    sans être l'auteur. / The operator takes down on report."""
    from django.test import Client

    django_user_model.objects.create_user(
        username="operatrice", password="mot-de-passe-de-test", is_staff=True
    )
    console = Client()
    console.login(username="operatrice", password="mot-de-passe-de-test")

    console.post(reverse("capsules:retirer_capsule", args=[ma_clameur.uuid]))

    ma_clameur.refresh_from_db()
    assert ma_clameur.statut == StatutCapsule.RETIREE


@pytest.mark.django_db
def test_une_clameur_retiree_quitte_la_liste_et_explique_au_porteur_du_ticket(client, ma_clameur):
    client.post(reverse("capsules:retirer_capsule", args=[ma_clameur.uuid]))

    assert str(ma_clameur.uuid) not in client.get("/").content.decode()
    page = client.get(reverse("capsules:lire_capsule", args=[ma_clameur.uuid]))
    assert page.status_code == 200, "le ticket collé ne doit jamais mener à un 404"


@pytest.mark.django_db
def test_le_bouton_de_retrait_ne_s_affiche_que_pour_l_auteur(client, ma_clameur):
    from django.test import Client

    a_moi = client.get(reverse("capsules:lire_capsule", args=[ma_clameur.uuid]))
    chez_un_autre = Client().get(reverse("capsules:lire_capsule", args=[ma_clameur.uuid]))

    assert "Retirer" in a_moi.content.decode()
    assert "Retirer" not in chez_un_autre.content.decode()


# ------------------------------------------------------ le second ticket

@pytest.fixture
def console(django_user_model):
    from django.test import Client

    django_user_model.objects.create_user(
        username="operateur", password="mot-de-passe-de-test", is_staff=True
    )
    navigateur = Client()
    navigateur.login(username="operateur", password="mot-de-passe-de-test")
    return navigateur


@pytest.mark.django_db
def test_le_staff_peut_demander_un_second_ticket(console, ma_clameur):
    from impression.models import JobImpression

    avant = JobImpression.objects.filter(capsule=ma_clameur).count()
    console.post(reverse("capsules:reimprimer_capsule", args=[ma_clameur.uuid]))

    assert JobImpression.objects.filter(capsule=ma_clameur).count() == avant + 1


@pytest.mark.django_db
def test_l_auteur_seul_ne_peut_pas_relancer_l_imprimante(client, ma_clameur):
    """Le rouleau se vide vite, et l'affiche se photographie : la relance
    reste un geste d'opérateur. / The roll empties fast; reprinting stays an
    operator's move."""
    from impression.models import JobImpression

    avant = JobImpression.objects.filter(capsule=ma_clameur).count()
    reponse = client.post(reverse("capsules:reimprimer_capsule", args=[ma_clameur.uuid]))

    assert reponse.status_code in (302, 403), "un non-staff ne doit pas passer"
    assert JobImpression.objects.filter(capsule=ma_clameur).count() == avant


@pytest.mark.django_db
def test_deux_tickets_de_la_meme_clameur_portent_deux_numeros_sunmi(reglages, ma_clameur):
    """SANS CELA, LE SECOND TICKET NE SORT JAMAIS. Le numéro de commande est
    la clé d'idempotence côté Sunmi, qui déduplique dessus : c'est ce qui
    empêche Celery d'imprimer deux fois en redélivrant une tâche. Mais deux
    JOBS distincts sont deux demandes distinctes — et doivent porter deux
    numéros, sinon Sunmi ignore le second en silence et le papier reste
    vierge, le job marqué « envoyé ».
    / Sunmi deduplicates on the trade_no: two distinct jobs must carry two
      distinct numbers, or the second ticket never prints and nobody is told.
    """
    from impression.mock import MockBackend
    from impression.models import JobImpression

    premier = JobImpression.objects.create(capsule=ma_clameur, reglages=reglages)
    second = JobImpression.objects.create(capsule=ma_clameur, reglages=reglages)

    backend = MockBackend(reglages)
    numero_1 = backend.print_ticket(ma_clameur, "https://x.example/c/1", reference=premier.pk)
    numero_2 = backend.print_ticket(ma_clameur, "https://x.example/c/1", reference=second.pk)

    assert numero_1 != numero_2


@pytest.mark.django_db
def test_rejouer_le_meme_job_garde_le_meme_numero(reglages, ma_clameur):
    """L'autre moitié : Celery redélivre les tâches interrompues, et un rejeu
    du MÊME job doit rester idempotent — sinon un redéploiement au mauvais
    moment fait sortir un doublon. / A redelivered task must stay idempotent."""
    from impression.mock import MockBackend
    from impression.models import JobImpression

    job = JobImpression.objects.create(capsule=ma_clameur, reglages=reglages)
    backend = MockBackend(reglages)

    assert (backend.print_ticket(ma_clameur, "https://x.example/c/1", reference=job.pk)
            == backend.print_ticket(ma_clameur, "https://x.example/c/1", reference=job.pk))
