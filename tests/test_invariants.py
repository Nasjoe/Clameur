"""LES TESTS LES PLUS IMPORTANTS DU PROJET.

Ils gardent une seule promesse : un ticket deja colle sur un mur ne doit jamais
mener a une page vide.
/ THE MOST IMPORTANT TESTS: a ticket already stuck on a wall must never lead
to an empty page.
"""

import pytest

from capsules.models import StatutCapsule
from capsules.publication import publier
from impression.models import JobImpression, StatutJob


@pytest.mark.django_db
def test_I1_une_capsule_publiee_est_lisible_par_tous_les_navigateurs(capsule):
    """Sans normalisation AAC, une capsule enregistree sur Android est muette
    sur iPhone — et le premier a scanner un ticket est presque toujours son
    auteur, sur son propre telephone."""
    publier(capsule)
    capsule.refresh_from_db()

    assert capsule.statut == StatutCapsule.PUBLIEE
    assert capsule.audio_diffusion, "pas d'AAC produit : muet sur iPhone"
    assert capsule.audio_diffusion.name.endswith(".m4a")


@pytest.mark.django_db
def test_I2_la_publication_survit_a_un_redis_mort(capsule, monkeypatch):
    """La base est la source de verite, jamais la file."""

    def redis_est_mort(*args, **kwargs):
        raise ConnectionError("Redis est mort")

    monkeypatch.setattr("impression.tasks.envoyer_le_ticket.delay", redis_est_mort)
    monkeypatch.setattr("capsules.tasks.transcrire.delay", redis_est_mort)

    publier(capsule)  # ne doit pas lever
    capsule.refresh_from_db()

    assert capsule.statut == StatutCapsule.PUBLIEE
    job = JobImpression.objects.get(capsule=capsule)
    assert job.statut == StatutJob.EN_ATTENTE, "le job attend une relance en console"


@pytest.mark.django_db
def test_I3_la_publication_survit_a_une_imprimante_absente(
    capsule, borne_sans_imprimante
):
    capsule.borne = borne_sans_imprimante
    capsule.save()

    publier(capsule)
    capsule.refresh_from_db()

    assert capsule.statut == StatutCapsule.PUBLIEE
    assert JobImpression.objects.filter(capsule=capsule).exists()


@pytest.mark.django_db
def test_un_echec_de_ffmpeg_ne_bloque_pas_la_publication(capsule, monkeypatch):
    """Publier ne doit JAMAIS echouer : on se replie sur l'original."""
    monkeypatch.setattr(
        "capsules.publication.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("ffmpeg absent")),
    )

    publier(capsule)
    capsule.refresh_from_db()

    assert capsule.statut == StatutCapsule.PUBLIEE
    assert capsule.audio_a_servir == capsule.audio_original
    assert capsule.erreur_enrichissement != ""


@pytest.mark.django_db
def test_l_audio_servi_est_lisible_en_streaming(capsule):
    """L'atome `moov` doit preceder `mdat`.

    Quand ffmpeg le laisse en fin de fichier — son comportement par defaut —
    le navigateur affiche « 0:00 / 0:00 » et la barre de progression reste
    inerte tant que tout n'est pas telecharge. Sur un reseau de festival, le
    passant abandonne avant.
    / The moov atom must come first, or the player shows no duration.
    """
    publier(capsule)
    capsule.refresh_from_db()

    with capsule.audio_diffusion.open("rb") as fichier:
        entete = fichier.read(4096)

    position_moov = entete.find(b"moov")
    position_mdat = entete.find(b"mdat")
    assert position_moov != -1, "atome moov absent de l'entete : fichier non streamable"
    assert position_mdat == -1 or position_moov < position_mdat, (
        "moov apres mdat : durée inconnue et déplacement impossible"
    )
