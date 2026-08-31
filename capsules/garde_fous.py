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
        f"limite:{action}:ip:{adresse_ip(request)}",
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


def adresse_ip(request) -> str:
    """L'adresse du visiteur, dans une chaine Traefik -> nginx -> gunicorn.

    `X-Forwarded-For` s'ecrit de gauche a droite, chaque proxy ajoutant a la
    fin l'adresse de celui qui l'a appele. Notre chaine produit donc :

        "<client>, <Traefik>"          vu par Django

    car Traefik pose l'adresse du client, puis nginx ajoute celle de Traefik.
    Le visiteur est l'AVANT-DERNIER element.

    Les deux extremites sont des pieges, et j'ai teste les deux :
    - le PREMIER element est ecrit par le client. S'y fier laisse n'importe qui
      forger une adresse differente a chaque requete et vider le rouleau.
    - le DERNIER est l'adresse de notre propre proxy, identique pour tout le
      monde. S'y fier fait compter tous les visiteurs sur un seul compteur :
      apres cinq clameurs, la borne se ferme a tous pendant une heure.
    / Both ends are traps: the first is client-written, the last is our own
      proxy — shared by everyone, so the borne would lock out all visitors.
    """
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    maillons = [m.strip() for m in transmise.split(",") if m.strip()]
    if len(maillons) >= 2:
        return maillons[-2]
    if maillons:
        return maillons[-1]
    return request.META.get("REMOTE_ADDR", "inconnue")
