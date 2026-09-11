"""Le QR du ticket dessine un picto (QArt) et doit toujours se lire.
/ The ticket's QR code draws a pictogram and must always scan."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import zxingcpp

from impression.escpos_builder import construire_le_ticket
from impression.mock import MockBackend, decoder_escpos

URL = "https://clameur.example/c/3f2b9c1e"
COMMANDE_RASTER = b"\x1d\x76\x30\x00"
COMMANDE_QR_NATIF = b"\x1d\x28\x6b"
DOSSIER_DES_PICTOS = Path(__file__).resolve().parent.parent / "impression" / "pictos"


def les_images_du_ticket(octets: bytes) -> list[np.ndarray]:
    """Relit chaque image `GS v 0` du flux : 0 = noir, 255 = blanc.
    / Reads back every raster image of the stream."""
    images = []
    debut = octets.find(COMMANDE_RASTER)
    while debut >= 0:
        octets_par_ligne = octets[debut + 4] + 256 * octets[debut + 5]
        lignes = octets[debut + 6] + 256 * octets[debut + 7]
        donnees = octets[debut + 8: debut + 8 + octets_par_ligne * lignes]
        bits = np.unpackbits(np.frombuffer(donnees, dtype=np.uint8))
        images.append(np.where(bits.reshape(lignes, octets_par_ligne * 8), 0, 255).astype(np.uint8))
        debut = octets.find(COMMANDE_RASTER, debut + 8 + len(donnees))
    return images


def le_texte_du_qr(image: np.ndarray) -> str:
    lus = zxingcpp.read_barcodes(image)
    assert lus, "le QR imprime ne se lit pas"
    return lus[0].text


@pytest.mark.django_db
def test_le_qr_du_ticket_se_lit_et_mene_a_la_capsule(capsule):
    octets = construire_le_ticket(capsule, dots_par_ligne=576, url_capsule=URL)

    images = les_images_du_ticket(octets)
    assert len(images) == 1, "sans photo, la seule image du ticket est le QR"
    adresse, _diese, chiffres = le_texte_du_qr(images[0]).partition("#")
    assert adresse == URL
    assert chiffres.isdigit(), "apres le #, QArt ne met que des chiffres"
    assert COMMANDE_QR_NATIF not in octets


@pytest.mark.django_db
def test_le_qr_tient_dans_la_laize_de_58_mm(capsule):
    octets = construire_le_ticket(capsule, dots_par_ligne=384, url_capsule=URL)

    image = les_images_du_ticket(octets)[0]
    assert image.shape[1] <= 384
    assert le_texte_du_qr(image).startswith(URL + "#")


@pytest.mark.django_db
def test_le_picto_est_tire_parmi_tous_ceux_du_dossier(capsule):
    with patch("impression.escpos_builder.random.choice", side_effect=lambda pictos: pictos[0]) as tirage:
        construire_le_ticket(capsule, 576, URL)

    pictos_proposes = {chemin.name for chemin in tirage.call_args.args[0]}
    assert pictos_proposes == {chemin.name for chemin in DOSSIER_DES_PICTOS.glob("*.png")}
    assert len(pictos_proposes) > 1


@pytest.mark.django_db
def test_si_qart_echoue_le_ticket_garde_un_qr_natif(capsule):
    with patch("impression.escpos_builder.dessiner_le_qr", side_effect=RuntimeError("panne")):
        octets = construire_le_ticket(capsule, 576, URL)

    assert COMMANDE_QR_NATIF in octets
    assert URL in "\n".join(decoder_escpos(octets))


@pytest.mark.django_db
def test_sans_picto_le_ticket_garde_un_qr_natif(capsule, tmp_path):
    with patch("impression.escpos_builder.DOSSIER_DES_PICTOS", tmp_path):
        octets = construire_le_ticket(capsule, 576, URL)

    assert COMMANDE_QR_NATIF in octets


def test_le_mock_resume_une_image_au_lieu_d_en_imprimer_les_octets():
    image = COMMANDE_RASTER + bytes([2, 0, 3, 0]) + b"ABCDEF"
    assert decoder_escpos(b"avant\n" + image + b"apres\n") == ["avant", "[image 16x3]", "apres"]


@pytest.mark.django_db
def test_les_mentions_legales_creditent_les_pictos(client):
    """La licence CC BY de game-icons exige un credit visible de qui voit le
    ticket, pas seulement du depot. / CC BY requires a public credit."""
    page = client.get("/mentions-legales").content.decode()
    for mention in ("game-icons.net", "CC BY 3.0", "Delapouite", "Lorc", "Phosphor Icons", "rsc.io/qr"):
        assert mention in page


@pytest.mark.django_db
def test_le_mock_affiche_l_url_du_qr(reglages, capsule, caplog):
    caplog.set_level("INFO", logger="impression.mock")
    MockBackend(reglages).print_ticket(capsule, URL)
    assert URL in caplog.text
