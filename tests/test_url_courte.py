"""L'URL courte du ticket : `/c/<8 premiers caracteres de l'UUID>`.
/ The ticket's short URL: the first 8 characters of the UUID."""

from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from capsules.models import Capsule, StatutCapsule
from impression.tasks import url_de_la_capsule
from tests.conftest import un_vrai_wav


def code_court(capsule) -> str:
    return capsule.uuid.hex[:8]


@pytest.mark.django_db
def test_l_url_courte_mene_a_la_capsule(client, capsule_publiee):
    reponse = client.get(f"/c/{code_court(capsule_publiee)}")
    assert reponse.status_code == 302
    assert reponse.url == f"/c/{capsule_publiee.uuid}"


@pytest.mark.django_db
def test_l_url_courte_d_un_brouillon_n_existe_pas(client, capsule):
    """Rediriger revelerait l'UUID complet, qui suffit a publier le brouillon.
    / Redirecting would leak the full UUID, which is enough to publish."""
    assert client.get(f"/c/{code_court(capsule)}").status_code == 404


@pytest.mark.django_db
def test_une_capsule_retiree_reste_joignable_par_son_url_courte(client, capsule_publiee):
    capsule_publiee.statut = StatutCapsule.RETIREE
    capsule_publiee.save()
    assert client.get(f"/c/{code_court(capsule_publiee)}").status_code == 302


@pytest.mark.django_db
def test_une_url_courte_inconnue_rend_404(client):
    assert client.get("/c/00000000").status_code == 404


@pytest.mark.django_db
def test_une_nouvelle_capsule_evite_un_prefixe_deja_pris(capsule):
    meme_prefixe = UUID(code_court(capsule) + "f" * 24)
    libre = uuid4()
    with patch("capsules.models.uuid4", side_effect=[meme_prefixe, libre]):
        nouvelle = Capsule.objects.create(reglages=capsule.reglages, audio_original=un_vrai_wav())

    assert nouvelle.uuid == libre


@pytest.mark.django_db
def test_sur_un_doublon_ancien_la_premiere_capsule_creee_gagne(client, capsule_publiee):
    """Le ticket le plus ancien est colle depuis le plus longtemps : il garde
    sa capsule. / The oldest ticket keeps its capsule."""
    cadette = Capsule.objects.create(
        uuid=UUID(code_court(capsule_publiee) + "f" * 24),
        reglages=capsule_publiee.reglages,
        audio_original=un_vrai_wav(),
        statut=StatutCapsule.PUBLIEE,
    )
    Capsule.objects.filter(pk=capsule_publiee.pk).update(
        creee_le=timezone.now() - timedelta(days=1)
    )

    reponse = client.get(f"/c/{code_court(cadette)}")
    assert reponse.url == f"/c/{capsule_publiee.uuid}"


@pytest.mark.django_db
def test_le_ticket_porte_l_url_courte(capsule, settings):
    settings.URL_PUBLIQUE = "https://clameur.example/"
    assert url_de_la_capsule(capsule) == f"https://clameur.example/c/{code_court(capsule)}"
