"""Les tests ne touchent a rien de reel. / Tests touch nothing real."""

import os

from clameur.celery import app


def test_aucun_identifiant_sunmi_ne_fuit_du_env():
    """Le .env de dev porte de vrais identifiants Sunmi. Sans neutralisation,
    `GET /nouvelle` interrogeait le vrai `onlineStatus`, et un backend cense
    refuser envoyait un vrai `pushContent`.
    / Real Sunmi credentials leaked from the .env into the tests."""
    for variable in ("SUNMI_APP_ID", "SUNMI_APP_KEY", "SUNMI_PRINTER_SN"):
        assert not os.environ.get(variable), f"{variable} fuit du .env dans les tests"


def test_les_taches_n_atteignent_pas_le_vrai_courtier():
    """Un test en `transaction=True` deposait de vraies taches dans le Redis de
    dev, et le worker de dev les executait SUR LA BASE DE DEV : un vrai ticket
    pouvait sortir. Constate le 2026-09-11.
    / Tasks reached the dev worker, which ran them against the dev database."""
    assert app.conf.broker_url.startswith("memory://")
    assert app.conf.result_backend.startswith("cache+memory://")
