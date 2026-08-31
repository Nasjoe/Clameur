"""Le pilote Sunmi vendorise et ses quatre corrections.
/ The vendored Sunmi driver and its four fixes."""

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from impression.sunmi_cloud_printer import DIFFUSE_DITHER, THRESHOLD_DITHER, SunmiCloudPrinter


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


def test_le_tramage_par_diffusion_n_est_pas_le_defaut():
    """Garde-fou : le defaut du pilote est le seuillage, qui sort une photo en
    aplats noirs illisibles. Le builder DOIT passer DIFFUSE_DITHER explicitement.
    / The driver defaults to thresholding, unusable for a photo."""
    assert DIFFUSE_DITHER != THRESHOLD_DITHER
    import inspect

    signature = inspect.signature(SunmiCloudPrinter.appendImage)
    assert signature.parameters["mode"].default == THRESHOLD_DITHER


def test_le_contenu_du_ticket_part_en_hexadecimal():
    """body.content = ESC/POS encode en hexadecimal, pas en base64."""
    pilote = pilote_de_test()
    pilote.appendText("bonjour\n")
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value = MagicMock(status_code=200, text='{"code": 1}')
        pilote.pushContent(trade_no="t1", sn="SN", count=1)
    corps = faux_post.call_args.kwargs["data"].decode("utf-8")
    assert b"bonjour".hex() in corps
