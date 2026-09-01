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


# ------------------------------------------------ le corpus « pour de vrai »

# Les fixtures savent parler et penser comme le vrai service — sur demande.
#
# `--avec-mistral` N'EST PAS ACTIF PAR DEFAUT, ET C'EST LE POINT. La suite de
# tests tourne dans le conteneur, ou `MISTRAL_API_KEY` est presente : si la
# commande appelait l'API des qu'elle voit une cle, chaque `make test`
# partirait sur le reseau et sur la note de frais.
# / Never on by default: the test container has a key, and the suite must stay
#   offline and free.


@pytest.mark.django_db
def test_avec_mistral_les_vecteurs_viennent_du_modele():
    from unittest.mock import patch

    from capsules.management.commands.creer_des_clameurs import Command

    faux = [[0.5] * 1024, [0.25] * 1024, [0.125] * 1024, [0.0625] * 1024]

    # `_fabriquer_une_voix` est neutralisee : ce test parle des vecteurs, et
    # sans cela il partirait sur le reseau pour synthetiser quatre capsules.
    # / Voice generation is stubbed: this test is about vectors, not audio.
    with patch(
        "capsules.management.commands.creer_des_clameurs._vecteurs_du_modele",
        return_value=faux,
    ), patch.object(Command, "_fabriquer_une_voix", return_value=None):
        call_command("creer_des_clameurs", nombre=4, vider=True,
                     avec_mistral=True, verbosity=0)

    vecteurs = {tuple(c.embedding) for c in Capsule.objects.all()}
    assert vecteurs == {tuple(v) for v in faux}, (
        "les vecteurs du modèle n'ont pas été écrits en base"
    )


@pytest.mark.django_db
def test_sans_cle_le_corpus_se_fabrique_quand_meme(monkeypatch):
    """`make fixture` doit marcher sans clé : c'est la promesse du README.
    / The README promises fixtures work with no key at all."""
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    call_command("creer_des_clameurs", nombre=4, vider=True,
                 avec_mistral=True, verbosity=0)

    assert Capsule.objects.count() == 4
    for capsule in Capsule.objects.all():
        assert capsule.embedding is not None
        assert len(capsule.embedding) == 1024
        assert capsule.audio_diffusion


@pytest.mark.django_db
def test_une_clameur_parlee_dure_ce_que_dure_son_audio(monkeypatch):
    """Sur une capsule parlée, la durée affichée est celle du fichier, pas un
    tirage au sort : la fiche ne doit pas annoncer trois minutes pour trente
    secondes de voix. / A spoken capsule's duration is the file's own."""
    from unittest.mock import patch

    # Une clé factice, POSÉE EXPRÈS : la commande renonce à la synthèse quand
    # l'environnement n'en porte aucune, et ce test passerait alors pour de
    # mauvaises raisons chez qui n'a pas de clé — sans jamais rien synthétiser.
    # / A deliberate fake key: without one the command skips synthesis entirely,
    #   and this test would pass for the wrong reason.
    monkeypatch.setenv("MISTRAL_API_KEY", "clé-factice-jamais-appelée")

    from capsules.management.commands.creer_des_clameurs import CAPSULES_PARLEES

    def fausse_replique(texte, voix, dossier, index):
        import subprocess
        from pathlib import Path

        chemin = Path(dossier) / f"{index}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "3", str(chemin)],
            check=True, capture_output=True,
        )
        return chemin

    with patch(
        "capsules.management.commands.creer_des_clameurs._synthetiser_une_replique",
        side_effect=fausse_replique,
    ), patch(
        "capsules.management.commands.creer_des_clameurs._vecteurs_du_modele",
        return_value=None,
    ):
        call_command("creer_des_clameurs", nombre=8, vider=True,
                     avec_mistral=True, verbosity=0)

    parlees = [c for c in Capsule.objects.all() if c.transcription_raw.get("parlee")]
    assert len(parlees) == CAPSULES_PARLEES

    import subprocess

    for capsule in parlees:
        mesure = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", capsule.audio_diffusion.path],
            check=True, capture_output=True, text=True,
        )
        assert abs(capsule.duree_secondes - float(mesure.stdout)) <= 1, (
            f"{capsule.uuid} annonce {capsule.duree_secondes} s "
            f"pour {mesure.stdout.strip()} s d'audio"
        )


@pytest.mark.django_db
def test_un_lot_de_vecteurs_incomplet_ne_melange_pas_les_genres():
    """Si l'API rend moins de vecteurs que de clameurs, on garde le synthétique.

    `zip` s'arrêtait au plus court : les premières clameurs recevaient de vrais
    vecteurs, les suivantes gardaient leurs gaussiennes, et la constellation
    mélangeait deux espaces qui n'ont rien à voir — un ciel faux, sans un mot.
    / zip stopped at the shortest, silently mixing two unrelated spaces.
    """
    from unittest.mock import patch

    from capsules.management.commands.creer_des_clameurs import Command

    with patch(
        "capsules.management.commands.creer_des_clameurs._vecteurs_du_modele",
        return_value=[[0.5] * 1024, [0.25] * 1024],   # deux vecteurs pour quatre
    ), patch.object(Command, "_fabriquer_une_voix", return_value=None):
        call_command("creer_des_clameurs", nombre=4, vider=True,
                     avec_mistral=True, verbosity=0)

    vecteurs = [tuple(c.embedding) for c in Capsule.objects.all()]
    assert tuple([0.5] * 1024) not in vecteurs, (
        "un lot incomplet a quand même été écrit : la constellation mélange "
        "des vecteurs réels et des vecteurs synthétiques"
    )


@pytest.mark.django_db
def test_un_vecteur_de_mauvaise_dimension_ne_rentre_pas_en_base():
    """Même exigence que la tâche `embarquer` : un vecteur tronqué fausserait
    la projection entière sans que rien ne le signale.

    Ici il ferait pire que fausser : `bulk_update` lèverait côté base, APRÈS
    que cent clameurs et leurs fichiers ont été créés, et l'appel n'est protégé
    par aucun `try`. / A truncated vector would blow up bulk_update after a
    hundred capsules and their files had already been written.
    """
    from unittest.mock import patch

    from capsules.management.commands.creer_des_clameurs import Command

    with patch(
        "capsules.management.commands.creer_des_clameurs._vecteurs_du_modele",
        return_value=[[0.5] * 512] * 4,          # 512 au lieu de 1024
    ), patch.object(Command, "_fabriquer_une_voix", return_value=None):
        call_command("creer_des_clameurs", nombre=4, vider=True,
                     avec_mistral=True, verbosity=0)

    assert Capsule.objects.count() == 4
    for capsule in Capsule.objects.all():
        assert len(capsule.embedding) == 1024
