"""Ce que toute page doit connaitre. / What every page needs to know."""

from django.conf import settings


def marque(request):
    """L'URL publique absolue, pour les metadonnees de partage.

    UNE URL DE PARTAGE NE PEUT PAS ETRE RELATIVE : `og:image` et `og:url` sont
    lues par un serveur tiers — celui de Signal, de Mastodon ou de WhatsApp —
    qui n'a aucun moyen de deviner notre domaine. C'est la meme raison qui fait
    vivre URL_PUBLIQUE pour le QR des tickets.
    / Share metadata is read by a third-party server that cannot guess our
      domain: the same reason URL_PUBLIQUE exists for the tickets' QR codes.
    """
    return {"url_publique": settings.URL_PUBLIQUE.rstrip("/")}
