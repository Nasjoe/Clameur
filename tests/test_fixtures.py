"""Le corpus de démonstration.

Ces fixtures ne sont pas décoratives : elles servent à voir la mise en page
avec de vrais volumes, et à préparer la constellation du sous-projet 2. Un
corpus sans structure sémantique ne dirait rien d'une projection.
/ The demo corpus also seeds the future constellation.
"""

import pytest
from django.core.management import call_command

from capsules.models import Capsule, StatutCapsule, Tag


@pytest.fixture
def petit_corpus(db):
    call_command("creer_des_clameurs", nombre=8, vider=True, verbosity=0)
    return Capsule.objects.all()


def test_les_clameurs_sont_publiees_et_ecoutables(petit_corpus):
    assert petit_corpus.count() == 8
    for capsule in petit_corpus:
        assert capsule.statut == StatutCapsule.PUBLIEE
        assert capsule.audio_diffusion, f"{capsule.uuid} sans audio de diffusion"
        assert capsule.duree_secondes > 0


def test_l_audio_produit_est_lisible_en_streaming(petit_corpus):
    """Meme exigence que pour une vraie capsule : `moov` avant `mdat`."""
    with petit_corpus.first().audio_diffusion.open("rb") as fichier:
        entete = fichier.read(4096)
    position_moov, position_mdat = entete.find(b"moov"), entete.find(b"mdat")
    assert position_moov != -1
    assert position_mdat == -1 or position_moov < position_mdat


def test_chaque_clameur_porte_un_vecteur_de_1024_dimensions(petit_corpus):
    for capsule in petit_corpus:
        assert capsule.embedding is not None
        assert len(capsule.embedding) == 1024


def test_les_vecteurs_forment_des_amas_par_theme(db):
    """Le voisin le plus proche doit appartenir au MEME THEME.

    On compare les themes et non les tags : deux clameurs d'un meme theme
    tirent leurs tags parmi cinq possibles et peuvent n'en partager aucun.
    Mesurer les tags testerait le tirage au sort, pas la structure des vecteurs.
    / Compare themes, not tags: same-theme capsules may share no tag at all.

    Des vecteurs aleatoires donneraient un nuage uniforme, ou l'on ne saurait
    pas si une projection fonctionne. Ce test garantit qu'il y a une structure.
    / Random vectors would leave nothing to show.
    """
    from pgvector.django import CosineDistance

    from capsules.management.commands.creer_des_clameurs import THEMES

    theme_du_tag = {
        nom_de_tag: theme["nom"] for theme in THEMES for nom_de_tag in theme["tags"]
    }

    def theme_de(capsule):
        for lien in capsule.tags_de_capsule.all():
            if lien.tag.nom in theme_du_tag:
                return theme_du_tag[lien.tag.nom]
        return None

    call_command("creer_des_clameurs", nombre=32, vider=True, verbosity=0)

    accords = 0
    references = list(
        Capsule.objects.prefetch_related("tags_de_capsule__tag")[:12]
    )
    for reference in references:
        voisin = (
            Capsule.objects.exclude(pk=reference.pk)
            .order_by(CosineDistance("embedding", reference.embedding))
            .prefetch_related("tags_de_capsule__tag")
            .first()
        )
        if theme_de(reference) and theme_de(reference) == theme_de(voisin):
            accords += 1

    assert accords >= 10, (
        f"seulement {accords}/12 voisins sont du meme theme : les vecteurs "
        "ne forment pas d'amas exploitables"
    )


def test_les_tags_et_les_pseudos_sont_varies(petit_corpus):
    assert Tag.objects.count() >= 4
    assert len({c.pseudo for c in petit_corpus}) >= 4


def test_vider_supprime_aussi_les_fichiers(petit_corpus):
    chemins = [c.audio_diffusion.path for c in petit_corpus]
    call_command("creer_des_clameurs", nombre=2, vider=True, verbosity=0)

    from pathlib import Path

    assert not any(Path(chemin).exists() for chemin in chemins), "fichiers orphelins"
    assert Capsule.objects.count() == 2
