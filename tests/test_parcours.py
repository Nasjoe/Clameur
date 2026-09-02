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
def test_l_accueil_affiche_le_texte_du_lieu(client, reglages):
    reponse = client.get("/nouvelle")
    assert reponse.status_code == 200
    assert "Dépose ta clameur." in reponse.content.decode()


@pytest.mark.django_db
def test_l_accueil_signale_une_imprimante_hors_ligne(client, reglages, monkeypatch):
    monkeypatch.setattr(
        "capsules.views.interroger_l_imprimante",
        lambda reglages: {"en_ligne": False, "message": "hors ligne"},
    )
    contenu = client.get("/nouvelle").content.decode()
    assert "ne répond pas" in contenu


@pytest.mark.django_db
@pytest.mark.parametrize(
    "nom,type_mime",
    [("a.webm", "audio/webm"), ("a.m4a", "audio/mp4"), ("a.ogg", "audio/ogg")],
)
def test_tout_format_de_navigateur_est_accepte(client, reglages, nom, type_mime):
    """Une liste blanche rejetterait un navigateur minoritaire en silence."""
    reponse = client.post(
        "/nouvelle/capsule", {"audio": un_fichier_audio(nom, type_mime)}
    )
    assert reponse.status_code == 200, f"{type_mime} rejeté"
    assert Capsule.objects.filter(uuid=reponse.json()["uuid"]).exists()


@pytest.mark.django_db
def test_une_borne_fermee_refuse_les_enregistrements(client, reglages):
    reglages.active = False
    reglages.save()
    reponse = client.post("/nouvelle/capsule", {"audio": un_fichier_audio()})
    assert reponse.status_code == 403


@pytest.mark.django_db
def test_on_ne_peut_pas_vider_le_rouleau_de_papier(client, reglages):
    """Le QR de l'affiche se photographie : sans limite, on imprime en boucle."""
    codes = [
        client.post("/nouvelle/capsule", {"audio": un_fichier_audio()}).status_code
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
def test_publier_cree_le_ticket_et_les_tags_de_l_auteur(client, reglages):
    creation = client.post("/nouvelle/capsule", {"audio": un_vrai_wav()})
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
def test_la_purge_ne_supprime_rien_sans_le_drapeau(reglages, capsule):
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
def test_l_affiche_est_reservee_a_l_operateur(client, reglages):
    """L'affiche est un outil d'operateur, pas une page publique."""
    reponse = client.get("/affiche")
    assert reponse.status_code in (302, 403), "affiche accessible sans authentification"


@pytest.mark.django_db
def test_l_affiche_porte_le_qr_du_lieu(client, reglages, django_user_model):
    operateur = django_user_model.objects.create_user(
        username="operateur", password="motdepasse-de-test", is_staff=True
    )
    client.force_login(operateur)

    contenu = client.get("/affiche").content.decode()
    assert "<svg" in contenu, "aucun QR code sur l'affiche"
    assert "/nouvelle" in contenu
    assert "A4" in contenu, "format d'impression non défini"


@pytest.mark.django_db
def test_un_meme_locuteur_garde_la_meme_couleur(client, capsule_publiee):
    """Colorer au fil des segments donnerait deux teintes a la meme personne
    qui parle deux fois : la transcription deviendrait illisible."""
    capsule_publiee.transcription_raw = {"segments": [
        {"speaker": "voix 1", "start": 0, "end": 1, "text": "Premier."},
        {"speaker": "voix 2", "start": 1, "end": 2, "text": "Deuxième."},
        {"speaker": "voix 1", "start": 2, "end": 3, "text": "Le premier revient."},
    ]}
    capsule_publiee.save()

    from capsules.views import preparer_les_paroles

    segments = preparer_les_paroles(capsule_publiee.transcription_raw["segments"])
    assert segments[0]["couleur"] == segments[2]["couleur"], "même voix, couleurs différentes"
    assert segments[0]["couleur"] != segments[1]["couleur"], "deux voix, même couleur"


@pytest.mark.django_db
def test_le_garde_fou_identifie_le_visiteur_et_non_le_proxy(client, reglages):
    """Dans la chaîne Traefik → nginx → gunicorn, `X-Forwarded-For` vaut
    « client, Traefik » : le visiteur est l'avant-dernier.

    Les deux extrémités sont des pièges. Le premier élément est écrit par le
    client — s'y fier laisse forger une adresse par requête. Le dernier est
    l'adresse de notre propre proxy, la même pour tout le monde : s'y fier
    ferme la reglages à tous après cinq clameurs.
    / Both ends are traps: one is forgeable, the other is shared by everyone.
    """
    from capsules.garde_fous import adresse_ip

    def requete(entete):
        fausse = client.request().wsgi_request
        fausse.META["HTTP_X_FORWARDED_FOR"] = entete
        return fausse

    # Chaîne réelle : le client, puis Traefik ajouté par nginx.
    assert adresse_ip(requete("203.0.113.7, 172.20.0.3")) == "203.0.113.7"

    # Le client tente de se cacher derrière une adresse forgée : elle passe
    # devant, la vraie reste en avant-dernier.
    assert adresse_ip(requete("1.2.3.4, 203.0.113.7, 172.20.0.3")) == "203.0.113.7"

    # Sans proxy (développement), on retombe sur l'adresse directe.
    directe = client.request().wsgi_request
    directe.META.pop("HTTP_X_FORWARDED_FOR", None)
    directe.META["REMOTE_ADDR"] = "127.0.0.1"
    assert adresse_ip(directe) == "127.0.0.1"


@pytest.mark.django_db
def test_deux_visiteurs_derriere_le_meme_proxy_ne_se_bloquent_pas(client, reglages):
    """Le compteur doit distinguer les visiteurs, pas les additionner sous
    l'adresse du proxy."""
    from capsules.garde_fous import limite_atteinte

    def requete_de(ip):
        fausse = client.request().wsgi_request
        fausse.META["HTTP_X_FORWARDED_FOR"] = f"{ip}, 172.20.0.3"
        return fausse

    for _ in range(6):
        limite_atteinte(requete_de("203.0.113.7"), "creation")

    assert limite_atteinte(requete_de("203.0.113.7"), "creation") is True
    assert limite_atteinte(requete_de("198.51.100.9"), "creation") is False, (
        "un visiteur innocent est bloqué par le compteur d'un autre"
    )


def test_les_locuteurs_sont_nommes_en_francais_et_dans_l_ordre():
    """`speaker_1` est l'identifiant de Voxtral, pas un mot pour un visiteur.

    On numérote dans l'ordre d'apparition, quelle que soit l'étiquette rendue
    par l'API : « speaker_0 », « speaker_7 » ou « voix » deviennent Voix 1,
    Voix 2… / Voxtral's identifier is not a word for a visitor.
    """
    from capsules.views import preparer_les_paroles

    paroles = preparer_les_paroles([
        {"speaker": "speaker_3", "start": 0, "end": 1, "text": "Premier."},
        {"speaker": "speaker_1", "start": 1, "end": 2, "text": "Deuxième."},
        {"speaker": "speaker_3", "start": 2, "end": 3, "text": "Le premier revient."},
    ])
    assert [p["speaker"] for p in paroles] == ["Voix 1", "Voix 2", "Voix 1"]


def test_deux_repliques_de_suite_du_meme_locuteur_n_en_font_qu_une():
    """Voxtral coupe au silence, pas au tour de parole : une même personne
    produit trois segments d'affilée, et la page les affichait comme trois
    interventions séparées, chacune avec son étiquette.
    / Voxtral splits on silence, not on turns: one person yielded three
      labelled blocks in a row."""
    from capsules.views import preparer_les_paroles

    paroles = preparer_les_paroles([
        {"speaker": "speaker_1", "start": 0.0, "end": 1.5, "text": "Trente-deux ans."},
        {"speaker": "speaker_1", "start": 1.8, "end": 3.0, "text": "Mon père y allait."},
        {"speaker": "speaker_2", "start": 3.2, "end": 4.0, "text": "Et personne n'a rien vu."},
    ])

    assert len(paroles) == 2
    assert paroles[0]["text"] == "Trente-deux ans. Mon père y allait."
    assert paroles[0]["start"] == 0.0
    assert paroles[0]["end"] == 3.0, "la parole fusionnée doit courir jusqu'à la fin"
    assert paroles[1]["speaker"] == "Voix 2"


def test_une_seule_voix_garde_une_seule_couleur():
    from capsules.views import preparer_les_paroles

    paroles = preparer_les_paroles([
        {"speaker": "voix", "start": 0, "end": 1, "text": "Un."},
        {"speaker": "voix", "start": 2, "end": 3, "text": "Deux."},
    ])
    assert len(paroles) == 1
    assert paroles[0]["speaker"] == "Voix 1"
