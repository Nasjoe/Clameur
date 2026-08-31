"""La transcription qui arrive après coup, par WebSocket.
/ Transcription arriving later, over WebSocket.

La fiche doit s'afficher SANS attendre Voxtral : une capsule publiée est
écoutable tout de suite, et son texte la rejoint quand il est prêt.
/ The card shows without waiting for Voxtral; the text catches up.
"""

import pytest
from channels.testing import WebsocketCommunicator

from capsules.consumers import GROUPE, ConstellationConsumer
from capsules.diffusion import diffuser_la_transcription
from capsules.models import Capsule


@pytest.mark.django_db
def test_une_fiche_sans_transcription_s_affiche_quand_meme(client, corpus_pret):
    """Sinon une clameur fraîchement publiée serait invisible le temps de
    l'enrichissement — or c'est précisément là qu'on veut la voir."""
    capsule = corpus_pret.first()
    Capsule.objects.filter(pk=capsule.pk).update(
        transcription_raw=None, transcription_texte="", erreur_enrichissement=""
    )
    contenu = client.get("/").content.decode()

    assert f'id="transcription-{capsule.uuid}"' in contenu, "pas de cible pour le swap"
    assert "Transcription en cours" in contenu


@pytest.mark.django_db
def test_les_positions_sortent_avec_un_point_decimal(client, corpus_pret):
    """En français, Django rend un flottant avec une VIRGULE : data-x="0,54".
    Number() renvoie alors NaN et toutes les étoiles disparaissent, sans la
    moindre erreur en console. `{% localize off %}` est ce qui l'évite."""
    import re

    contenu = client.get("/").content.decode()
    valeurs = re.findall(r'data-x="([^"]+)"', contenu)

    assert valeurs, "aucune position rendue"
    fautives = [valeur for valeur in valeurs if "," in valeur]
    assert not fautives, f"positions localisées : {fautives[:5]} sur {len(valeurs)}"
    assert all(float(valeur) == float(valeur) for valeur in valeurs)


@pytest.mark.django_db
def test_le_fragment_diffuse_porte_le_swap_oob(corpus_pret, monkeypatch):
    """Sans hx-swap-oob, HTMX ignorerait le message : rien ne se mettrait à jour."""
    envois = []
    monkeypatch.setattr(
        "capsules.diffusion.async_to_sync",
        lambda fonction: lambda *args, **kwargs: envois.append(args),
    )

    capsule = corpus_pret.first()
    diffuser_la_transcription(capsule)

    assert envois, "rien n'a été diffusé"
    groupe, message = envois[0]
    assert groupe == GROUPE
    assert message["type"] == "fragment.html"
    # outerHTML et non innerHTML : innerHTML laisserait les attributs de
    # l'élément en place, dont l'indicateur d'attente.
    assert 'hx-swap-oob="outerHTML"' in message["html"]
    assert f'id="transcription-{capsule.uuid}"' in message["html"]


@pytest.mark.django_db
def test_une_panne_de_la_couche_de_canaux_ne_fait_pas_echouer_la_tache(
    corpus_pret, monkeypatch
):
    """Le temps réel est un confort : le texte est déjà en base et apparaîtra
    au prochain chargement."""
    def couche_morte(*args, **kwargs):
        raise ConnectionError("Redis est mort")

    monkeypatch.setattr("capsules.diffusion.get_channel_layer", couche_morte)
    diffuser_la_transcription(corpus_pret.first())  # ne doit pas lever


@pytest.mark.asyncio
async def test_le_consumer_accepte_et_relaie_un_fragment():
    """Le consumer ne parle pas : il rejoint le groupe et relaie ce qu'on y
    publie. / The consumer joins the group and relays what is published."""
    communicateur = WebsocketCommunicator(ConstellationConsumer.as_asgi(), "/ws/constellation")
    connecte, _ = await communicateur.connect()
    assert connecte

    from channels.layers import get_channel_layer

    await get_channel_layer().group_send(
        GROUPE, {"type": "fragment.html", "html": "<div id='essai'>bonjour</div>"}
    )
    recu = await communicateur.receive_from(timeout=2)
    assert "bonjour" in recu

    await communicateur.disconnect()
