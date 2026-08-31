"""Garde-fous anti-abus. / Anti-abuse guards.

Le QR de l'affiche se photographie, et /b/<slug> fonctionne depuis n'importe
ou : sans limite, quelqu'un peut faire cracher des tickets en continu et vider
le rouleau au milieu d'un evenement.
/ The poster's QR can be photographed: without a limit, someone empties the roll.
"""

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

CAPSULES_PAR_HEURE = 5
DUREE_DE_LA_FENETRE = 3600


def limite_atteinte(request, action: str) -> bool:
    """Rend True si l'auteur de la requete a deja trop sollicite la borne.

    NE LEVE JAMAIS, ET C'EST LE POINT IMPORTANT. Le backend Redis de Django
    propage ses erreurs de connexion : sans ce filet, un Redis tombe ferait
    repondre 500 a toute la chaine de capture, et la voix du visiteur serait
    perdue. On s'ouvre plutot que de se fermer — un rouleau de papier vaut
    moins qu'une parole.
    / Django's Redis backend propagates connection errors: without this net a
      dead Redis would 500 the whole capture path. Fail open: a paper roll is
      worth less than a voice.
    """
    try:
        return _limite_atteinte(request, action)
    except Exception:
        logger.exception("garde-fou indisponible, on laisse passer")
        return False


def _limite_atteinte(request, action: str) -> bool:
    if not request.session.session_key:
        request.session.save()

    empreintes = [
        f"limite:{action}:ip:{_adresse_ip(request)}",
        f"limite:{action}:session:{request.session.session_key}",
    ]
    for empreinte in empreintes:
        compte = cache.get(empreinte, 0)
        if compte >= CAPSULES_PAR_HEURE:
            return True

    for empreinte in empreintes:
        # add() ne pose la valeur que si la cle est absente : c'est ce qui fait
        # demarrer la fenetre au premier appel, sans la repousser ensuite.
        # / add() only sets when absent: the window starts once and does not slide.
        cache.add(empreinte, 0, DUREE_DE_LA_FENETRE)
        try:
            cache.incr(empreinte)
        except ValueError:
            cache.set(empreinte, 1, DUREE_DE_LA_FENETRE)
    return False


def _adresse_ip(request) -> str:
    """L'adresse telle que NOTRE proxy l'a vue, pas celle que le client annonce.

    `X-Forwarded-For` s'ecrit de gauche a droite : le premier element vient du
    client et se forge en une ligne de curl, le dernier est ajoute par le
    proxy le plus proche de nous. Prendre le premier revenait a offrir le
    contournement du garde-fou a qui sait poser un en-tete.
    / The first XFF entry is client-supplied and trivially forged; the last is
      the one our own proxy appended.
    """
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmise:
        return transmise.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "inconnue")
