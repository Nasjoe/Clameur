"""Les backends d'impression. / Printing backends."""

import pytest

from impression.escpos_builder import construire_le_ticket
from impression.mock import MockBackend, decoder_escpos
from impression.sunmi_cloud import SunmiCloudBackend


@pytest.mark.django_db
def test_le_ticket_porte_le_pseudo_et_l_url_de_la_capsule(capsule):
    """Le mock construit les MEMES octets que le backend reel : ce test est
    donc un vrai test du ticket, pas d'un bouchon."""
    url = f"https://clameur.example/c/{capsule.uuid}"
    octets = construire_le_ticket(capsule, dots_par_ligne=576, url_capsule=url)
    texte = "\n".join(decoder_escpos(octets))

    assert "anonyme" in texte
    assert url in texte, "l'URL du QR doit voyager en clair dans le flux"
    assert "CLAMEUR" in texte


@pytest.mark.django_db
def test_le_ticket_annonce_la_duree_honnetement(capsule):
    capsule.duree_secondes = 125
    texte = "\n".join(
        decoder_escpos(construire_le_ticket(capsule, 576, "https://x.example/c/1"))
    )
    assert "2 min 05 s" in texte


@pytest.mark.django_db
def test_les_tags_de_l_auteur_apparaissent_sur_le_ticket(capsule):
    from capsules.models import Tag, TagDeCapsule

    tag = Tag.objects.create(nom="souvenir")
    TagDeCapsule.objects.create(capsule=capsule, tag=tag, origine=TagDeCapsule.AUTEUR)
    texte = "\n".join(
        decoder_escpos(construire_le_ticket(capsule, 576, "https://x.example/c/1"))
    )
    assert "souvenir" in texte


@pytest.mark.django_db
def test_can_print_refuse_une_borne_sans_numero_de_serie(borne_sans_imprimante, monkeypatch):
    monkeypatch.setenv("SUNMI_APP_ID", "a")
    monkeypatch.setenv("SUNMI_APP_KEY", "k")
    possible, message = SunmiCloudBackend(borne_sans_imprimante).can_print()
    assert possible is False
    assert "série" in message


@pytest.mark.django_db
def test_can_print_refuse_des_credentials_absents(borne, monkeypatch):
    monkeypatch.delenv("SUNMI_APP_ID", raising=False)
    monkeypatch.setenv("SUNMI_APP_KEY", "k")
    possible, message = SunmiCloudBackend(borne).can_print()
    assert possible is False
    assert "SUNMI_APP_ID" in message


@pytest.mark.django_db
def test_une_api_sunmi_injoignable_ne_leve_jamais(borne, monkeypatch):
    """Une panne de l'API ne doit pas empecher d'afficher la page d'accueil."""
    monkeypatch.setenv("SUNMI_APP_ID", "a")
    monkeypatch.setenv("SUNMI_APP_KEY", "k")
    monkeypatch.setattr(
        "impression.sunmi_cloud_printer.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(OSError("reseau coupe")),
    )
    en_ligne, message = SunmiCloudBackend(borne).est_en_ligne()
    assert en_ligne is False
    assert "injoignable" in message


@pytest.mark.django_db
def test_le_mock_imprime_toujours(borne, capsule):
    possible, _ = MockBackend(borne).can_print()
    assert possible is True
    assert MockBackend(borne).print_ticket(capsule, "https://x.example/c/1").startswith("mock_")


# --------------------------------------------------- la file d'impression

@pytest.mark.django_db
def test_un_ticket_envoye_n_est_jamais_rejoue(capsule, borne):
    """Celery redélivre les tâches interrompues (`acks_late`). Sans garde, un
    redéploiement au mauvais moment ferait sortir un second ticket identique —
    et le papier ne se rembobine pas.
    / acks_late redelivers interrupted tasks; the paper does not rewind."""
    from unittest.mock import patch

    from impression.models import JobImpression, StatutJob
    from impression.tasks import envoyer_le_ticket

    job = JobImpression.objects.create(
        capsule=capsule, borne=borne, statut=StatutJob.ENVOYE, trade_no="deja"
    )
    with patch("impression.tasks.choisir_le_backend") as backend:
        assert envoyer_le_ticket(job.pk) == StatutJob.ENVOYE
    assert not backend.called, "le ticket a été réimprimé"


@pytest.mark.django_db
def test_un_backend_qui_refuse_marque_le_job_en_echec(
    capsule, borne_sans_imprimante, monkeypatch
):
    """Les identifiants sont posés pour que le backend RÉEL soit choisi : sans
    eux, c'est le backend de simulation qui prend la main, et lui imprime
    toujours. / Credentials set so the real backend is picked."""
    from impression.models import JobImpression, StatutJob
    from impression.tasks import envoyer_le_ticket

    monkeypatch.setenv("SUNMI_APP_ID", "a")
    monkeypatch.setenv("SUNMI_APP_KEY", "k")

    job = JobImpression.objects.create(capsule=capsule, borne=borne_sans_imprimante)
    assert envoyer_le_ticket(job.pk) == StatutJob.ECHOUE

    job.refresh_from_db()
    assert job.tentatives == 1
    assert job.message_erreur, "l'échec doit dire pourquoi"


@pytest.mark.django_db
def test_un_envoi_reussi_conserve_le_numero_sunmi(capsule, borne, monkeypatch):
    """`trade_no` sert à interroger `printStatus` : sans lui, on ne peut plus
    savoir si le papier est sorti."""
    from impression.models import JobImpression, StatutJob
    from impression.tasks import envoyer_le_ticket

    class BackendQuiImprime:
        def can_print(self):
            return True, ""

        def print_ticket(self, capsule, url):
            return "N411_abcd1234_1700000000"

    monkeypatch.setattr("impression.tasks.choisir_le_backend", lambda b: BackendQuiImprime())
    job = JobImpression.objects.create(capsule=capsule, borne=borne)

    assert envoyer_le_ticket(job.pk) == StatutJob.ENVOYE
    job.refresh_from_db()
    assert job.trade_no == "N411_abcd1234_1700000000"


@pytest.mark.django_db
def test_le_numero_de_ticket_est_unique_par_capsule_et_stable(capsule, borne, monkeypatch):
    """`trade_no` est notre clé d'idempotence côté Sunmi, qui déduplique dessus.

    Il doit donc être DÉTERMINISTE : une tâche redélivrée par Celery — un
    redéploiement au mauvais moment — doit produire exactement le même numéro,
    sinon Sunmi ne voit pas le doublon et un second ticket sort. Y mettre
    l'horloge détruisait cette propriété.

    Et il doit rester unique d'une capsule à l'autre, y compris pour deux
    publications de la même seconde sur la même borne.
    / Deterministic so a redelivered task yields the same number, unique so two
      capsules never collide.
    """
    from unittest.mock import patch

    from capsules.models import Capsule

    autre = Capsule.objects.create(borne=borne, audio_original=capsule.audio_original)
    monkeypatch.setenv("SUNMI_APP_ID", "a")
    monkeypatch.setenv("SUNMI_APP_KEY", "k")

    backend = SunmiCloudBackend(borne)
    with patch.object(SunmiCloudBackend, "_pilote"), \
         patch("impression.sunmi_cloud.construire_le_ticket", return_value=b""):
        premier = backend.print_ticket(capsule, "https://x.example/c/1")
        rejeu = backend.print_ticket(capsule, "https://x.example/c/1")
        second = backend.print_ticket(autre, "https://x.example/c/2")

    assert premier == rejeu, "un rejeu doit produire le même numéro, sinon Sunmi réimprime"
    assert premier != second, "deux capsules ne peuvent pas partager un numéro"


@pytest.mark.django_db
def test_le_backend_de_simulation_ne_se_dit_jamais_en_ligne(borne):
    """Sans identifiants Sunmi, ce backend prend la main et n'imprime rien.
    Répondre « en ligne » ferait promettre un ticket à chaque visiteur d'une
    borne qui n'en sortira jamais."""
    en_ligne, message = MockBackend(borne).est_en_ligne()
    assert en_ligne is False
    assert "simulée" in message
