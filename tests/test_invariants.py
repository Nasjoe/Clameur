"""LES TESTS LES PLUS IMPORTANTS DU PROJET.

Ils gardent une seule promesse : un ticket deja colle sur un mur ne doit jamais
mener a une page vide.
/ THE MOST IMPORTANT TESTS: a ticket already stuck on a wall must never lead
to an empty page.
"""

import pytest

from capsules.models import Capsule, StatutCapsule
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
def test_I2_la_publication_survit_a_un_redis_mort(
    capsule, monkeypatch, django_capture_on_commit_callbacks
):
    """La base est la source de verite, jamais la file."""

    def redis_est_mort(*args, **kwargs):
        raise ConnectionError("Redis est mort")

    monkeypatch.setattr("impression.tasks.envoyer_le_ticket.delay", redis_est_mort)
    monkeypatch.setattr("capsules.tasks.transcrire.delay", redis_est_mort)

    # `django_capture_on_commit_callbacks(execute=True)` EST INDISPENSABLE.
    # Les enqueues passent par `transaction.on_commit`, et sous `django_db` la
    # transaction du test est annulee : sans cette enveloppe, les rappels ne
    # partent jamais et le test valide du vide — on pourrait supprimer tout le
    # `try/except` de `_enfiler_sans_risque` sans qu'il bronche.
    # / Without this the on_commit callbacks never run and the test checks nothing.
    with django_capture_on_commit_callbacks(execute=True):
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


# ------------------------------------ les invariants sur le chemin HTTP réel

@pytest.mark.django_db
def test_I2_la_publication_survit_a_un_cache_mort(client, borne, monkeypatch):
    """L'ancien test I2 ne patchait que `.delay` : il validait un invariant que
    le chemin HTTP ne tenait pas. Le garde-fou anti-abus interroge le cache
    Redis AVANT d'atteindre `publier()`, et le backend Redis de Django propage
    ses erreurs de connexion — un Redis tombé faisait donc répondre 500 à toute
    la chaîne de capture, et la voix du visiteur était perdue.
    / The old I2 test only patched .delay, so it validated an invariant the HTTP
      path did not hold: the throttle hits Redis before publier() is reached.
    """
    from tests.conftest import un_vrai_wav

    creation = client.post(f"/b/{borne.slug}/capsule", {"audio": un_vrai_wav()})
    uuid = creation.json()["uuid"]

    def cache_mort(*args, **kwargs):
        raise ConnectionError("Redis est mort")

    monkeypatch.setattr("django.core.cache.cache.get", cache_mort)
    monkeypatch.setattr("django.core.cache.cache.set", cache_mort)
    monkeypatch.setattr("django.core.cache.cache.add", cache_mort)
    monkeypatch.setattr("django.core.cache.cache.incr", cache_mort)

    reponse = client.post(f"/c/{uuid}/publier", {"pseudo": "Nina"})

    assert reponse.status_code == 200, "un cache mort ne doit pas faire perdre la voix"
    capsule = Capsule.objects.get(uuid=uuid)
    assert capsule.statut == StatutCapsule.PUBLIEE


@pytest.mark.django_db
def test_la_capture_survit_a_un_cache_mort(client, borne, monkeypatch):
    from tests.conftest import un_vrai_wav

    def cache_mort(*args, **kwargs):
        raise ConnectionError("Redis est mort")

    monkeypatch.setattr("django.core.cache.cache.get", cache_mort)
    monkeypatch.setattr("django.core.cache.cache.set", cache_mort)
    monkeypatch.setattr("django.core.cache.cache.add", cache_mort)

    assert client.get(f"/b/{borne.slug}").status_code == 200
    reponse = client.post(f"/b/{borne.slug}/capsule", {"audio": un_vrai_wav()})
    assert reponse.status_code == 200


@pytest.mark.django_db
def test_republier_la_meme_capsule_reste_sans_effet(client, borne):
    """Un visiteur qui réappuie après une réponse perdue ne doit ni voir une
    erreur ni faire sortir un second ticket.

    Ce test est SÉQUENTIEL : il couvre l'idempotence, pas la course. Celle-ci
    est vérifiée par le test à deux fils ci-dessous.
    / Sequential: covers idempotence, not the race. See the threaded test below."""
    from impression.models import JobImpression
    from tests.conftest import un_vrai_wav

    uuid = client.post(f"/b/{borne.slug}/capsule", {"audio": un_vrai_wav()}).json()["uuid"]

    premiere = client.post(f"/c/{uuid}/publier", {"pseudo": "Nina"})
    seconde = client.post(f"/c/{uuid}/publier", {"pseudo": "Nina"})

    assert premiere.status_code == 200
    # La seconde réussit aussi : du point de vue du visiteur l'opération a
    # abouti, et son ticket sort. Lui répondre une erreur le ferait partir en
    # croyant avoir échoué. / Idempotent from the visitor's side.
    assert seconde.status_code == 200
    assert JobImpression.objects.filter(capsule__uuid=uuid).count() == 1


@pytest.mark.django_db
def test_le_repli_audio_annonce_son_vrai_type(capsule, monkeypatch):
    """Quand ffmpeg échoue, c'est le fichier d'origine qui est servi. L'annoncer
    en `audio/mp4` était pire que de ne rien annoncer : le navigateur refuse de
    décoder un fichier dont le type ne correspond pas, sans jamais essayer
    autre chose — et le mode dégradé promis par I1 ne fonctionnait pas.
    / Mislabelling the fallback made the browser refuse to decode it."""
    monkeypatch.setattr(
        "capsules.publication.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("ffmpeg absent")),
    )
    capsule.audio_original.name = "capsules/x/original_capsule.webm"
    capsule.save()

    publier(capsule)
    capsule.refresh_from_db()

    assert not capsule.audio_diffusion
    assert capsule.type_mime_a_servir == "audio/webm"


@pytest.mark.django_db
def test_une_photo_en_noir_et_blanc_n_empeche_pas_le_ticket(
    capsule, une_photo_en_noir_et_blanc
):
    """Une photo en niveaux de gris traversait la purge EXIF en mode `L` ; le
    pilote, qui indexe trois canaux par pixel, levait alors une IndexError. La
    capsule était publiée mais son ticket ne sortait jamais, et chaque relance
    échouait à l'identique.
    / A greyscale photo made every print attempt fail with an IndexError."""
    from capsules.photos import purger_les_exif
    from impression.escpos_builder import construire_le_ticket

    capsule.photo.save(
        "mono.jpg", purger_les_exif(une_photo_en_noir_et_blanc), save=True
    )

    octets = construire_le_ticket(capsule, 576, "https://x.example/c/1")
    assert len(octets) > 100, "le ticket n'a pas été construit"


@pytest.mark.django_db(transaction=True)
def test_deux_publications_simultanees_n_impriment_qu_un_ticket(borne):
    """LA COURSE, POUR DE VRAI — deux requêtes qui partent en même temps.

    Le test séquentiel ci-dessus passerait même sans verrou : le second POST
    y trouve toujours la capsule déjà publiée. Ici les deux fils entrent
    ensemble, et sans `select_for_update` ils lisent tous deux `brouillon`,
    normalisent tous deux, et créent deux `JobImpression` — donc deux tickets.
    / The sequential test would pass without the lock; this one would not.
    """
    import threading

    from django.db import connections
    from django.test import Client

    from impression.models import JobImpression
    from tests.conftest import un_vrai_wav

    client = Client()
    uuid = client.post(f"/b/{borne.slug}/capsule", {"audio": un_vrai_wav()}).json()["uuid"]

    depart = threading.Barrier(2)
    reponses = []

    def publier_depuis_un_fil():
        try:
            depart.wait(timeout=5)
            reponses.append(Client().post(f"/c/{uuid}/publier", {"pseudo": "Nina"}).status_code)
        finally:
            # Un fil Django doit rendre sa connexion, sinon la base garde une
            # transaction ouverte et le test suivant se bloque.
            # / A Django thread must close its connection or the next test hangs.
            connections.close_all()

    fils = [threading.Thread(target=publier_depuis_un_fil) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    assert reponses == [200, 200], f"réponses inattendues : {reponses}"
    assert JobImpression.objects.filter(capsule__uuid=uuid).count() == 1, (
        "deux tickets sortiraient de l'imprimante"
    )
