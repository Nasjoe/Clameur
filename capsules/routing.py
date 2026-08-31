"""Routes WebSocket. / WebSocket routes."""

from django.urls import path

from capsules.consumers import ConstellationConsumer

motifs_websocket = [
    path("ws/constellation", ConstellationConsumer.as_asgi()),
]
