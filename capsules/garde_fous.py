"""Garde-fous anti-abus. / Anti-abuse guards.

Le QR de l'affiche se photographie, et /b/<slug> fonctionne depuis n'importe
ou : sans limite, quelqu'un peut faire cracher des tickets en continu et vider
le rouleau au milieu d'un evenement.
/ The poster's QR can be photographed: without a limit, someone empties the roll.
"""

from django.core.cache import cache

CAPSULES_PAR_HEURE = 5
DUREE_DE_LA_FENETRE = 3600


def limite_atteinte(request, action: str) -> bool:
    """Rend True si l'auteur de la requete a deja trop sollicite la borne."""
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
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmise:
        return transmise.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "inconnue")
