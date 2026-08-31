"""Diffusion des transcriptions terminees vers les pages ouvertes.
/ Pushes finished transcriptions to open pages.

UN SEUL GROUPE POUR TOUT LE MONDE, et non un groupe par capsule.
S'abonner a une centaine de groupes couterait une centaine d'allers-retours a
l'ouverture de la page, pour un volume de messages minuscule : une
transcription par clameur publiee, quelques-unes par heure au plus fort d'un
evenement. Chaque page recoit donc tout et n'applique que ce qui la concerne —
le swap OOB de HTMX ignore silencieusement une cible absente.
/ One shared group: subscribing to a hundred would cost far more than it saves,
and HTMX quietly ignores an OOB swap whose target is not on the page.
"""

from channels.generic.websocket import AsyncWebsocketConsumer

GROUPE = "constellation"


class ConstellationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(GROUPE, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(GROUPE, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """La page n'a rien a nous dire : on ecoute, on ne repond pas.
        / The page has nothing to tell us: we only listen."""
        return

    async def fragment_html(self, evenement):
        """Envoie un fragment HTML que HTMX inserera par swap OOB.
        / Sends an HTML fragment for HTMX to place with an OOB swap."""
        await self.send(text_data=evenement["html"])
