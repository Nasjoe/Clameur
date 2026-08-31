"""Le pilote Sunmi vendorise et ses quatre corrections.
/ The vendored Sunmi driver and its four fixes."""

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from impression.sunmi_cloud_printer import DIFFUSE_DITHER, SunmiCloudPrinter


def pilote_de_test():
    return SunmiCloudPrinter(576, app_id="a", app_key="k", printer_sn="SN")


def test_la_signature_hmac_est_conforme_au_protocole():
    """Sign = HMAC-SHA256(body + app_id + timestamp + nonce, cle = app_key)."""
    signature = pilote_de_test().generateSign(
        body='{"x":1}', timestamp="1700000000", nonce="000042"
    )
    attendu = hmac.new(
        key=b"k", msg=b'{"x":1}a1700000000000042', digestmod=hashlib.sha256
    ).hexdigest()
    assert signature == attendu


def test_les_appels_reseau_ont_un_timeout():
    """CORRECTION 1 : sans timeout, un worker Celery se bloque indefiniment."""
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value = MagicMock(status_code=200, text='{"code": 1}')
        pilote_de_test().onlineStatus("SN")
    assert faux_post.call_args.kwargs["timeout"] > 0, "appel reseau sans timeout"


def test_les_methodes_d_interrogation_retournent_le_json():
    """CORRECTION 4 : sans valeur de retour, le controle d'etat est irrealisable."""
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value = MagicMock(
            status_code=200, text='{"code": 1, "data": {"status": "online"}}'
        )
        resultat = pilote_de_test().onlineStatus("SN")
    assert resultat["data"]["status"] == "online"


def test_un_echec_http_leve_une_exception():
    """CORRECTION 3 : sans ce controle, un job echoue passerait pour envoye."""
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value = MagicMock(status_code=500, text="{}")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            pilote_de_test().onlineStatus("SN")


def test_un_refus_applicatif_de_sunmi_leve_une_exception():
    """HTTP 200 avec un corps d'erreur : le piege classique des routeurs."""
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value = MagicMock(
            status_code=200, text='{"code": 400, "msg": "device offline"}'
        )
        with pytest.raises(RuntimeError, match="device offline"):
            pilote_de_test().onlineStatus("SN")


@pytest.mark.django_db
def test_le_builder_demande_le_tramage_par_diffusion(capsule, une_photo):
    """Le defaut du pilote est le seuillage, qui sort une photo en aplats noirs
    illisibles. Ce test verifie que NOTRE builder impose la diffusion — retirer
    `mode=DIFFUSE_DITHER` de escpos_builder.py doit le faire echouer.
    / Checks our builder, not the driver's default: removing the explicit mode
      must break this test."""
    from unittest.mock import patch

    from impression.escpos_builder import construire_le_ticket

    capsule.photo.save("photo.jpg", une_photo, save=True)

    with patch.object(SunmiCloudPrinter, "appendImage") as fausse_image:
        construire_le_ticket(capsule, 576, "https://x.example/c/1")

    assert fausse_image.called, "la photo n'a pas ete posee sur le ticket"
    assert fausse_image.call_args.kwargs["mode"] == DIFFUSE_DITHER, (
        "tramage par seuillage : la photo sortira en aplats noirs"
    )


def test_le_contenu_du_ticket_part_en_hexadecimal():
    """body.content = ESC/POS encode en hexadecimal, pas en base64."""
    pilote = pilote_de_test()
    pilote.appendText("bonjour\n")
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value = MagicMock(status_code=200, text='{"code": 1}')
        pilote.pushContent(trade_no="t1", sn="SN", count=1)
    corps = faux_post.call_args.kwargs["data"].decode("utf-8")
    assert b"bonjour".hex() in corps


def test_le_calcul_de_gris_ne_deborde_pas():
    """Les composantes arrivent en `uint8` : la somme pondérée débordait dès
    que le pixel était clair. Un blanc pur rendait 7 au lieu de 255, donc les
    zones claires d'une photo ressortaient noires sur le papier.
    / uint8 components overflowed: pure white yielded 7 instead of 255."""
    import numpy as np
    from PIL import Image

    blanc = Image.new("RGB", (4, 4), (255, 255, 255))
    gris = pilote_de_test().convertToGray(blanc)

    assert int(np.asarray(gris).max()) == 255, "un blanc pur doit rester blanc"

    noir = Image.new("RGB", (4, 4), (0, 0, 0))
    assert int(np.asarray(pilote_de_test().convertToGray(noir)).max()) == 0


@pytest.mark.django_db
def test_une_image_en_niveaux_de_gris_ne_fait_pas_lever_le_pilote(tmp_path):
    """`convertToGray` indexe trois canaux par pixel : une image en mode `L`
    donne un tableau à deux dimensions et lève une IndexError.

    Le garde est dans le pilote et non à l'ingestion, parce qu'une image posée
    depuis la console d'administration ne passe pas par la purge EXIF.
    / The guard lives in the driver: admin-uploaded images bypass ingestion."""
    from PIL import Image

    chemin = tmp_path / "mono.png"
    Image.new("L", (32, 24), 128).save(chemin)

    pilote = pilote_de_test()
    pilote.appendImage(str(chemin), width=32)  # ne doit pas lever
    assert len(pilote.orderData) > 0
