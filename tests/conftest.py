"""Fixtures partagees. / Shared fixtures."""

import io
import wave

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from bornes.models import Borne
from capsules.models import Capsule, StatutCapsule


@pytest.fixture(autouse=True)
def statiques_sans_empreinte(settings):
    """Les tests ne passent jamais par `collectstatic`.

    En production, `ManifestStaticFilesStorage` exige un manifeste et fait
    echouer tout `{% static %}` qui n'y figure pas. Sans cette surcharge, la
    suite dependrait de la valeur de DEBUG dans le `.env` du moment : elle
    passerait chez l'un et casserait chez l'autre.
    / Tests never run collectstatic; without this the suite would depend on
      whatever DEBUG says in the local .env.
    """
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }


@pytest.fixture(autouse=True)
def medias_temporaires(settings, tmp_path):
    """Aucun test n'ecrit dans le vrai dossier medias.
    / No test writes into the real media folder."""
    settings.MEDIA_ROOT = tmp_path / "medias"
    return settings.MEDIA_ROOT


@pytest.fixture
def borne(db):
    return Borne.objects.create(
        slug="place-du-marche",
        nom="Place du marché",
        numero_serie_imprimante="N411245U00000",
        texte_accueil="Dépose ta clameur.",
    )


@pytest.fixture
def borne_sans_imprimante(db):
    return Borne.objects.create(slug="sans-imprimante", nom="Sans imprimante")


def un_fichier_audio(nom="capsule.webm", type_mime="audio/webm"):
    """Des octets quelconques : suffit aux tests qui ne convertissent rien.
    / Arbitrary bytes: enough for tests that never transcode."""
    return SimpleUploadedFile(nom, b"des-octets-audio", content_type=type_mime)


def un_vrai_wav(nom="capsule.wav", secondes=1):
    """Un WAV valide, fabrique sans ffmpeg (module `wave` de la stdlib).

    Les tests qui font tourner ffmpeg ont besoin d'un fichier qu'il accepte :
    des octets arbitraires le font echouer avec un code 183, et le test
    mesurerait alors la fixture au lieu du code.
    / A real WAV: arbitrary bytes make ffmpeg fail, testing the fixture instead.
    """
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as fichier:
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(8000)
        fichier.writeframes(b"\x00\x00" * 8000 * secondes)
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type="audio/wav")


@pytest.fixture
def capsule(borne):
    return Capsule.objects.create(
        borne=borne, pseudo="anonyme", audio_original=un_vrai_wav(), duree_secondes=42,
    )


@pytest.fixture
def capsule_publiee(capsule):
    capsule.statut = StatutCapsule.PUBLIEE
    capsule.save()
    return capsule


@pytest.fixture
def corpus_pret(db):
    """Un petit corpus deja projete, pret pour la page constellation.
    / A small, already-projected corpus."""
    from django.core.management import call_command

    call_command("creer_des_clameurs", nombre=6, vider=True, verbosity=0)
    call_command("projeter_la_constellation", verbosity=0)
    return Capsule.objects.all()
