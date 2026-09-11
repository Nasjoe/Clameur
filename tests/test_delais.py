"""Les delais de la publication, qui doivent s'emboiter.
/ Publishing timeouts, which must nest."""

import re
from pathlib import Path

from django.conf import settings

from capsules.publication import DUREE_MAX_FFMPEG, DUREE_MAX_FFPROBE


def test_les_delais_s_emboitent_ffmpeg_gunicorn_nginx():
    """ffmpeg + ffprobe < gunicorn <= nginx, AVEC DE LA MARGE.

    La publication est synchrone : ffmpeg convertit, puis ffprobe mesure la
    duree — meme quand ffmpeg a abandonne. Si gunicorn coupe avant la fin des
    deux, le repli sur l'audio d'origine n'est jamais atteint : la transaction
    est annulee et la capsule reste bloquee en brouillon. C'est deja arrive.
    Si nginx coupe avant gunicorn, le visiteur recoit une erreur alors que la
    publication aboutit derriere son dos.
    / If an outer layer gives up first, the capsule is stuck or the visitor misled.
    """
    racine = Path(settings.BASE_DIR)
    supervisord = (racine / "supervisord.conf").read_text()
    nginx = (racine / "nginx" / "clameur.conf").read_text()

    # La ligne de commande seulement : un commentaire qui citerait
    # « gunicorn ... --timeout N » ne doit pas etre pris pour elle.
    # / The command line only, never a comment quoting it.
    delai_gunicorn = int(
        re.search(r"^command=gunicorn .*--timeout (\d+)", supervisord, re.MULTILINE).group(1)
    )

    # Le bloc serveur seulement, AVANT `location /ws/`. Sans ce decoupage,
    # retirer le delai du serveur laissait la regex prendre celui des sockets
    # (3600 s), et le test restait vert. / Server block only, before /ws/.
    bloc_serveur = nginx.split("location /ws/")[0]
    delai_nginx = int(
        re.search(r"^\s*proxy_read_timeout (\d+)s;", bloc_serveur, re.MULTILINE).group(1)
    )

    assert DUREE_MAX_FFMPEG + DUREE_MAX_FFPROBE + 30 <= delai_gunicorn, (
        "gunicorn couperait la publication"
    )
    assert delai_gunicorn <= delai_nginx, "nginx couperait gunicorn"
