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
