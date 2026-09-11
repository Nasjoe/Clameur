"""Deposer un fichier audio : ce qui doit en sortir, et ce qui doit etre refuse.
/ Uploading an audio file: what must come out, and what must be refused."""

import io
import subprocess

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from capsules.models import Capsule
from capsules.publication import normaliser_l_audio
from tests.conftest import un_vrai_wav


def pistes_du_fichier(chemin) -> list[str]:
    """Les types de pistes d'un fichier, dans l'ordre : ["audio"], ["video", "audio"]…
    / The file's stream types, in order."""
    resultat = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(chemin),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return resultat.stdout.split()


@pytest.mark.django_db
def test_un_fichier_sans_son_est_refuse(client, reglages):
    """Une photo renommee en .mp3 passait jusqu'au ticket, avec « 0 s ».
    / A photo renamed .mp3 went all the way to the ticket."""
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 80, 40)).save(tampon, format="JPEG")
    faux_son = SimpleUploadedFile("photo.mp3", tampon.getvalue(), content_type="audio/mpeg")

    reponse = client.post("/nouvelle/capsule", {"audio": faux_son})

    assert reponse.status_code == 400
    assert "son" in reponse.json()["erreur"]
    assert not Capsule.objects.exists(), "un brouillon muet est reste en base"


@pytest.mark.django_db
def test_la_video_d_un_fichier_n_est_pas_gardee(reglages, tmp_path):
    """Sans `-vn`, ffmpeg reencodait l'image d'une video dans le m4a : lent
    pour la publication, et lourd a servir.
    / Without -vn the video track was re-encoded into the m4a too."""
    video = tmp_path / "video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=1",
            "-f", "lavfi", "-i", "sine=duration=1",
            "-c:v", "mpeg4", "-c:a", "aac", "-shortest",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    capsule = Capsule.objects.create(
        reglages=reglages,
        audio_original=SimpleUploadedFile("video.mp4", video.read_bytes()),
    )

    normaliser_l_audio(capsule)

    assert pistes_du_fichier(capsule.audio_diffusion.path) == ["audio"]


@pytest.mark.django_db
def test_la_duree_est_mesuree_meme_quand_ffmpeg_abandonne(reglages, monkeypatch):
    """Un fichier arrive avec une duree annoncee de 0 : c'est le serveur qui la
    mesure. Si ffmpeg depassait son delai, la mesure sautait avec lui, et le
    ticket annoncait « 0 s ».
    / The duration measurement used to be skipped along with ffmpeg."""
    from capsules import publication

    vrai_run = subprocess.run

    def ffmpeg_qui_abandonne(commande, *args, **kwargs):
        if commande[0] == "ffmpeg":
            raise subprocess.TimeoutExpired(commande, publication.DUREE_MAX_FFMPEG)
        return vrai_run(commande, *args, **kwargs)

    monkeypatch.setattr(publication.subprocess, "run", ffmpeg_qui_abandonne)
    capsule = Capsule.objects.create(reglages=reglages, audio_original=un_vrai_wav(secondes=3))

    normaliser_l_audio(capsule)

    assert capsule.duree_secondes == 3
