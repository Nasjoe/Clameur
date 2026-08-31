"""Les modeles et leurs garanties. / Models and their guarantees."""

import pytest

from bornes.models import Reglages
from capsules.models import Capsule, Tag, TagDeCapsule


@pytest.mark.django_db
def test_une_borne_a_des_valeurs_par_defaut_utilisables():
    reglages = Reglages.get_solo()
    assert reglages.dots_par_ligne == 576, "80 mm attendu par defaut"
    assert reglages.duree_max_secondes == 600, "garde-fou technique"
    assert reglages.active is True


def test_l_extension_pgvector_est_disponible(db):
    from django.db import connection

    with connection.cursor() as curseur:
        curseur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert curseur.fetchone() is not None, "extension pgvector absente"


@pytest.mark.django_db
def test_l_identifiant_public_n_est_pas_enumerable(reglages, capsule):
    """Un entier auto-incremente laisserait parcourir tout le corpus."""
    autre = Capsule.objects.create(reglages=reglages, audio_original=capsule.audio_original)
    assert capsule.uuid != autre.uuid
    assert len(str(capsule.uuid)) == 36


@pytest.mark.django_db
def test_un_tag_garde_la_trace_de_son_origine(capsule):
    """La parole de l'auteur et l'hypothese de la machine ne se melangent pas."""
    saisi = Tag.objects.create(nom="mémoire")
    devine = Tag.objects.create(nom="nostalgie")
    TagDeCapsule.objects.create(capsule=capsule, tag=saisi, origine=TagDeCapsule.AUTEUR)
    TagDeCapsule.objects.create(capsule=capsule, tag=devine, origine=TagDeCapsule.MACHINE)

    origines = {lien.tag.nom: lien.origine for lien in capsule.tags_de_capsule.all()}
    assert origines == {"mémoire": "auteur", "nostalgie": "machine"}


@pytest.mark.django_db
def test_l_audio_a_servir_se_replie_sur_l_original(capsule):
    """Mieux vaut un audio mal encode que pas d'audio du tout."""
    assert capsule.audio_diffusion.name in ("", None)
    assert capsule.audio_a_servir == capsule.audio_original


def test_le_type_mime_du_m4a_est_connu():
    """Sans cette declaration, Django sert l'audio en application/octet-stream
    et le navigateur affiche un lecteur muet a « 0:00 / 0:00 ».
    / Without it the browser receives octet-stream and shows a dead player."""
    import mimetypes

    type_devine, _encodage = mimetypes.guess_type("capsule.m4a")
    assert type_devine == "audio/mp4", f"m4a servi en {type_devine}"


def test_le_type_mime_des_polices_est_connu():
    """Sans cette déclaration, le `<link rel="preload" as="font">` est ignoré
    et la police est téléchargée deux fois."""
    import mimetypes

    type_devine, _encodage = mimetypes.guess_type("police.woff2")
    assert type_devine == "font/woff2", f"woff2 servi en {type_devine}"


@pytest.mark.django_db
def test_la_migration_pose_une_borne_sur_une_base_neuve():
    """Sans reglages, la page d'accueil n'affiche aucun bouton d'enregistrement et
    personne ne peut déposer la première clameur : le site reste vide
    définitivement, sans que rien ne l'explique.

    La migration `bornes.0002` en crée une si la table est vide. Elle a tourné
    au montage de cette base de test.
    / No reglages means no button, and nobody can post the first clameur.
    """
    assert Reglages.objects.exists(), "une base neuve doit porter une reglages"
