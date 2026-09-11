"""Les delais de la publication, qui doivent s'emboiter.
/ Publishing timeouts, which must nest."""

import re
from pathlib import Path

from django.conf import settings

from capsules.publication import DUREE_MAX_FFMPEG


def test_les_delais_s_emboitent_ffmpeg_gunicorn_nginx():
    """ffmpeg < gunicorn <= nginx, AVEC DE LA MARGE.

    La publication est synchrone et appelle ffmpeg. Si gunicorn coupe avant
    ffmpeg, le repli sur l'audio d'origine n'est jamais atteint : la
    transaction est annulee et la capsule reste bloquee en brouillon. C'est
    deja arrive. Si nginx coupe avant gunicorn, le visiteur recoit une erreur
    alors que la publication aboutit derriere son dos.
    / If an outer layer gives up first, the capsule is stuck or the visitor misled.
    """
    racine = Path(settings.BASE_DIR)
    supervisord = (racine / "supervisord.conf").read_text()
    nginx = (racine / "nginx" / "clameur.conf").read_text()

    delai_gunicorn = int(re.search(r"gunicorn .*--timeout (\d+)", supervisord).group(1))
    # Le premier `proxy_read_timeout` est celui du serveur ; celui de /ws/,
    # plus bas, ne concerne que les sockets. / The first one is server-wide.
    delai_nginx = int(re.search(r"^\s*proxy_read_timeout (\d+)s;", nginx, re.MULTILINE).group(1))

    assert DUREE_MAX_FFMPEG + 30 <= delai_gunicorn, "gunicorn couperait ffmpeg"
    assert delai_gunicorn <= delai_nginx, "nginx couperait gunicorn"
