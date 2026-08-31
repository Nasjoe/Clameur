"""Ce que le site dit de lui-même quand on le partage, et aux robots.
/ What the site says about itself when shared, and to robots.

Deux promesses tenues ici :
  - un lien de clameur envoyé dans une conversation arrive avec un titre,
    une description et une image — sinon personne ne l'ouvre ;
  - il n'emporte JAMAIS la parole enregistrée. Le test le plus important de
    ce fichier est celui qui vérifie que la transcription ne fuit pas.
"""

import re

import pytest

from capsules.models import Tag, TagDeCapsule


def metadonnees(html):
    """Les balises `og:` et `twitter:` de la page, sous forme de dictionnaire.
    / The page's og:/twitter: tags, as a dictionary."""
    trouvees = re.findall(
        r'<meta\s+(?:property|name)="((?:og|twitter):[^"]+)"\s+content="([^"]*)"', html
    )
    metas = {}
    for cle, valeur in trouvees:
        metas.setdefault(cle, []).append(valeur)
    return metas


# --------------------------------------------------------------- robots.txt

@pytest.mark.django_db
def test_robots_interdit_l_indexation_a_tout_le_monde(client):
    reponse = client.get("/robots.txt")
    assert reponse.status_code == 200
    assert reponse["Content-Type"].startswith("text/plain")
    texte = reponse.content.decode()
    # Le groupe generique doit refuser tout le site.
    assert re.search(r"^User-agent: \*\nDisallow: /$", texte, re.MULTILINE)


@pytest.mark.django_db
def test_robots_laisse_passer_les_depiauteurs_de_liens(client):
    """Plusieurs d'entre eux respectent robots.txt : un `Disallow` global
    priverait chaque lien partage de son apercu."""
    texte = client.get("/robots.txt").content.decode()
    for agent in ("Twitterbot", "facebookexternalhit", "Mastodon"):
        assert f"User-agent: {agent}" in texte
    assert "Allow: /" in texte


@pytest.mark.django_db
def test_chaque_page_porte_noindex(client, capsule_publiee, borne):
    """robots.txt empeche de parcourir, pas d'indexer une adresse trouvee
    ailleurs. La balise est le second verrou."""
    for adresse in ("/", f"/b/{borne.slug}", f"/c/{capsule_publiee.uuid}", "/mentions-legales"):
        html = client.get(adresse).content.decode()
        assert '<meta name="robots" content="noindex, nofollow">' in html, adresse


# ------------------------------------------------------------------- icônes

@pytest.mark.django_db
def test_favicon_ico_mene_a_l_icone(client):
    """Beaucoup d'agents tapent /favicon.ico sans lire le HTML."""
    reponse = client.get("/favicon.ico")
    assert reponse.status_code == 302
    assert "icone-32" in reponse["Location"]


@pytest.mark.django_db
def test_la_page_declare_ses_trois_icones(client):
    html = client.get("/").content.decode()
    assert 'type="image/svg+xml"' in html
    assert 'rel="apple-touch-icon"' in html
    assert '<meta name="theme-color"' in html


# ------------------------------------------------------------------ partage

@pytest.mark.django_db
def test_les_urls_de_partage_sont_absolues(client, capsule_publiee, settings):
    """Un serveur tiers — Signal, Mastodon — ne peut pas deviner notre domaine."""
    settings.URL_PUBLIQUE = "https://exemple.test"
    metas = metadonnees(client.get(f"/c/{capsule_publiee.uuid}").content.decode())
    assert metas["og:url"][0] == f"https://exemple.test/c/{capsule_publiee.uuid}"
    assert metas["og:image"][0].startswith("https://exemple.test/")


@pytest.mark.django_db
def test_l_apercu_d_une_clameur_dit_le_pseudo_les_mots_cles_et_la_duree(
    client, capsule_publiee
):
    tag = Tag.objects.create(nom="mémoire")
    TagDeCapsule.objects.create(
        capsule=capsule_publiee, tag=tag, origine=TagDeCapsule.AUTEUR
    )
    metas = metadonnees(client.get(f"/c/{capsule_publiee.uuid}").content.decode())
    assert "anonyme" in metas["og:title"][0]
    assert "mémoire" in metas["og:description"][0]
    assert "42" in metas["og:description"][0]


@pytest.mark.django_db
def test_l_apercu_n_emporte_JAMAIS_la_parole_enregistree(client, capsule_publiee):
    """LE TEST QUI COMPTE DANS CE FICHIER.

    La transcription est publique sur la page, et c'est un choix. La recopier
    dans un `og:description` est autre chose : elle part alors dans des
    historiques de conversation, des caches de plateformes et des apercus que
    son auteur n'a jamais vus.
    / The transcript is public on the page; that is a choice. Copying it into
      og:description sends it into conversation logs its author never saw.
    """
    phrase = "je me souviens du bruit de la grille"
    capsule_publiee.transcription_texte = phrase
    capsule_publiee.transcription_raw = {
        "segments": [{"speaker": "speaker_0", "start": 0, "end": 3, "text": phrase}]
    }
    capsule_publiee.save()

    html = client.get(f"/c/{capsule_publiee.uuid}").content.decode()
    assert phrase in html, "la transcription doit rester lisible SUR la page"

    for cle, valeurs in metadonnees(html).items():
        for valeur in valeurs:
            assert phrase not in valeur, f"la parole a fuite dans {cle}"


@pytest.mark.django_db
def test_une_clameur_avec_photo_partage_sa_photo(client, capsule_publiee, une_photo):
    from capsules.photos import purger_les_exif

    capsule_publiee.photo.save("photo.jpg", purger_les_exif(une_photo), save=True)
    metas = metadonnees(client.get(f"/c/{capsule_publiee.uuid}").content.decode())
    assert metas["og:image"][0].endswith(".jpg")
    # Une seule image : deux `og:image` laisseraient la plateforme choisir.
    assert len(metas["og:image"]) == 1


@pytest.mark.django_db
def test_sans_photo_la_clameur_partage_l_image_par_defaut(client, capsule_publiee):
    metas = metadonnees(client.get(f"/c/{capsule_publiee.uuid}").content.decode())
    assert "partage-defaut" in metas["og:image"][0]
    assert metas["og:image:width"][0] == "1200"


@pytest.mark.django_db
def test_la_constellation_annonce_le_nombre_de_clameurs(client, corpus_pret):
    metas = metadonnees(client.get("/").content.decode())
    assert "constellation" in metas["og:title"][0].lower()
    assert re.search(r"\d+ clameurs", metas["og:description"][0])
