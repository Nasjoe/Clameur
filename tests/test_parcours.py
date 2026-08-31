"""Le parcours du visiteur, de bout en bout. / The visitor's journey."""

import pytest
from django.core.cache import cache

from capsules.models import Capsule, StatutCapsule
from tests.conftest import un_fichier_audio, un_vrai_wav


@pytest.fixture(autouse=True)
def cache_vierge():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_l_accueil_affiche_le_texte_de_la_borne(client, borne):
    reponse = client.get(f"/b/{borne.slug}")
    assert reponse.status_code == 200
    assert "Dépose ta clameur." in reponse.content.decode()


@pytest.mark.django_db
def test_l_accueil_signale_une_imprimante_hors_ligne(client, borne, monkeypatch):
    monkeypatch.setattr(
        "capsules.views.interroger_l_imprimante",
        lambda borne: {"en_ligne": False, "message": "hors ligne"},
    )
    contenu = client.get(f"/b/{borne.slug}").content.decode()
    assert "ne répond pas" in contenu


@pytest.mark.django_db
@pytest.mark.parametrize(
    "nom,type_mime",
    [("a.webm", "audio/webm"), ("a.m4a", "audio/mp4"), ("a.ogg", "audio/ogg")],
)
def test_tout_format_de_navigateur_est_accepte(client, borne, nom, type_mime):
    """Une liste blanche rejetterait un navigateur minoritaire en silence."""
    reponse = client.post(
        f"/b/{borne.slug}/capsule", {"audio": un_fichier_audio(nom, type_mime)}
    )
    assert reponse.status_code == 200, f"{type_mime} rejeté"
    assert Capsule.objects.filter(uuid=reponse.json()["uuid"]).exists()


@pytest.mark.django_db
def test_une_borne_fermee_refuse_les_enregistrements(client, borne):
    borne.active = False
    borne.save()
    reponse = client.post(f"/b/{borne.slug}/capsule", {"audio": un_fichier_audio()})
    assert reponse.status_code == 403


@pytest.mark.django_db
def test_on_ne_peut_pas_vider_le_rouleau_de_papier(client, borne):
    """Le QR de l'affiche se photographie : sans limite, on imprime en boucle."""
    codes = [
        client.post(f"/b/{borne.slug}/capsule", {"audio": un_fichier_audio()}).status_code
        for _ in range(7)
    ]
    assert 429 in codes, "aucune limite : le rouleau se vide"


@pytest.mark.django_db
def test_un_brouillon_est_introuvable(client, capsule):
    assert client.get(f"/c/{capsule.uuid}").status_code == 404


@pytest.mark.django_db
def test_une_capsule_retiree_explique_au_lieu_de_renvoyer_404(client, capsule_publiee):
    capsule_publiee.statut = StatutCapsule.RETIREE
    capsule_publiee.save()
    reponse = client.get(f"/c/{capsule_publiee.uuid}")
    assert reponse.status_code == 200, "le ticket est colle dans la rue"
    assert "retirée" in reponse.content.decode()


@pytest.mark.django_db
def test_la_page_de_lecture_ne_tente_pas_l_autoplay(client, capsule_publiee):
    """iOS et Android bloquent l'autoplay : la page doit donner envie d'appuyer."""
    contenu = client.get(f"/c/{capsule_publiee.uuid}").content.decode()
    assert "autoplay" not in contenu
    assert "Écouter" in contenu


@pytest.mark.django_db
def test_l_ecoute_est_comptee_au_clic_pas_au_chargement(client, capsule_publiee):
    client.get(f"/c/{capsule_publiee.uuid}")
    capsule_publiee.refresh_from_db()
    assert capsule_publiee.nombre_ecoutes == 0, "comptee au chargement : fausse mesure"

    client.post(f"/c/{capsule_publiee.uuid}/ecoute")
    capsule_publiee.refresh_from_db()
    assert capsule_publiee.nombre_ecoutes == 1


@pytest.mark.django_db
def test_publier_cree_le_ticket_et_les_tags_de_l_auteur(client, borne):
    creation = client.post(f"/b/{borne.slug}/capsule", {"audio": un_vrai_wav()})
    uuid = creation.json()["uuid"]

    reponse = client.post(
        f"/c/{uuid}/publier", {"pseudo": "Nina", "tags": ["ville", "nuit"]}
    )
    assert reponse.status_code == 200

    capsule = Capsule.objects.get(uuid=uuid)
    assert capsule.statut == StatutCapsule.PUBLIEE
    assert capsule.pseudo == "Nina"
    assert {lien.tag.nom for lien in capsule.tags_de_capsule.all()} == {"ville", "nuit"}
    assert capsule.jobs_impression.exists()


@pytest.mark.django_db
def test_les_mentions_legales_sont_atteignables(client):
    assert client.get("/mentions-legales").status_code == 200


@pytest.mark.django_db
def test_la_purge_ne_supprime_rien_sans_le_drapeau(borne, capsule):
    from django.core.management import call_command
    from django.utils import timezone

    Capsule.objects.filter(pk=capsule.pk).update(
        creee_le=timezone.now() - timezone.timedelta(days=2)
    )
    call_command("purger_les_brouillons")
    assert Capsule.objects.filter(pk=capsule.pk).exists(), "supprimé sans confirmation"

    call_command("purger_les_brouillons", "--pour-de-vrai")
    assert not Capsule.objects.filter(pk=capsule.pk).exists()


@pytest.mark.django_db
def test_la_purge_epargne_les_capsules_publiees(capsule_publiee):
    from django.core.management import call_command
    from django.utils import timezone

    Capsule.objects.filter(pk=capsule_publiee.pk).update(
        creee_le=timezone.now() - timezone.timedelta(days=30)
    )
    call_command("purger_les_brouillons", "--pour-de-vrai")
    assert Capsule.objects.filter(pk=capsule_publiee.pk).exists()


@pytest.mark.django_db
def test_l_affiche_est_reservee_a_l_operateur(client, borne):
    """L'affiche est un outil d'operateur, pas une page publique."""
    reponse = client.get(f"/b/{borne.slug}/affiche")
    assert reponse.status_code in (302, 403), "affiche accessible sans authentification"


@pytest.mark.django_db
def test_l_affiche_porte_le_qr_de_la_borne(client, borne, django_user_model):
    operateur = django_user_model.objects.create_user(
        username="operateur", password="motdepasse-de-test", is_staff=True
    )
    client.force_login(operateur)

    contenu = client.get(f"/b/{borne.slug}/affiche").content.decode()
    assert "<svg" in contenu, "aucun QR code sur l'affiche"
    assert f"/b/{borne.slug}" in contenu
    assert "A4" in contenu, "format d'impression non défini"
