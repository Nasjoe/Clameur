"""Point d'entree ASGI : HTTP classique et WebSocket.
/ ASGI entry point: plain HTTP and WebSocket."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clameur.settings")

# L'application HTTP doit etre construite AVANT d'importer quoi que ce soit
# qui touche aux modeles : le registre des applications n'est pas encore pret.
# / Build the HTTP app before importing anything that touches models.
application_http = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from capsules.routing import motifs_websocket

application = ProtocolTypeRouter(
    {
        "http": application_http,
        # AllowedHostsOriginValidator refuse les connexions venant d'un autre
        # domaine : sans lui, n'importe quel site pourrait ouvrir une socket
        # vers Clameur depuis le navigateur d'un visiteur.
        # / Without this, any site could open a socket to Clameur.
        "websocket": AllowedHostsOriginValidator(URLRouter(motifs_websocket)),
    }
)
