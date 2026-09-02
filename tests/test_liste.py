"""La page d'accueil : la liste des clameurs, et sa recherche.

Le ciel est en sommeil depuis le 2026-09-01. Ce que la page doit tenir
maintenant est plus simple, et plus important : toute clameur publiée y est,
tout de suite, et on peut retrouver celle dont on se souvient d'un mot.
/ The sky is dormant; the list must show every published clameur at once, and
  let you find the one you remember a word of.
"""

import pytest
from django.utils import timezone

from capsules.models import Capsule, StatutCapsule, Tag, TagDeCapsule


def une_clameur(reglages, **champs):
    valeurs = {
        "reglages": reglages,
        "statut": StatutCapsule.PUBLIEE,
        "duree_secondes": 42,
        "publiee_le": timezone.now(),
    }
    valeurs.update(champs)
    return Capsule.objects.create(**valeurs)


@pytest.fixture
def corpus(reglages):
    """Trois clameurs, dont une SANS vecteur ni position : c'est le cas normal
    desormais. / Three clameurs, one with no vector at all: now the normal case."""
    marche = une_clameur(
        reglages, titre="Le marché du mercredi", pseudo="Rosa",
        transcription_texte="C'est le seul moment où tout le monde se parle.",
        publiee_le=timezone.now() - timezone.timedelta(hours=2),
    )
    tag = Tag.objects.create(nom="quartier")
    TagDeCapsule.objects.create(capsule=marche, tag=tag, origine=TagDeCapsule.AUTEUR)

    boulangerie = une_clameur(
        reglages, titre="La boulangerie ferme", pseudo="Ibrahim",
        transcription_texte="Trente-deux ans qu'elle était là.",
        publiee_le=timezone.now() - timezone.timedelta(hours=1),
    )
    nuit = une_clameur(
        reglages, titre="Trois heures du matin", pseudo="Odette",
        transcription_texte="La ville a une autre respiration.",
    )
    return {"marche": marche, "boulangerie": boulangerie, "nuit": nuit}


@pytest.mark.django_db
def test_l_accueil_montre_les_clameurs_de_la_plus_recente_a_la_plus_ancienne(client, corpus):
    page = client.get("/").content.decode()
    positions = [page.index(str(c.uuid)) for c in
                 (corpus["nuit"], corpus["boulangerie"], corpus["marche"])]
    assert positions == sorted(positions), "l'ordre n'est pas du plus récent au plus ancien"


@pytest.mark.django_db
def test_une_clameur_sans_vecteur_est_dans_la_liste(client, corpus):
    """LE TROU QUE LE CIEL CREUSAIT. Une clameur fraîchement publiée n'avait ni
    vecteur ni position, et restait invisible jusqu'au prochain recalcul —
    lancé à la main. Pendant un événement, les clameurs du jour n'existaient
    pas. / A freshly published clameur used to stay invisible until the next
    manual projection."""
    for capsule in corpus.values():
        assert capsule.embedding is None and capsule.position_x is None
        assert str(capsule.uuid) in client.get("/").content.decode()


@pytest.mark.django_db
def test_une_clameur_retiree_ou_en_brouillon_n_est_pas_dans_la_liste(client, corpus, reglages):
    retiree = une_clameur(reglages, titre="Retirée", statut=StatutCapsule.RETIREE)
    brouillon = une_clameur(reglages, titre="Brouillon", statut=StatutCapsule.BROUILLON)

    page = client.get("/").content.decode()
    assert str(retiree.uuid) not in page
    assert str(brouillon.uuid) not in page


# ------------------------------------------------------------- la recherche

@pytest.mark.django_db
@pytest.mark.parametrize("requete, attendue", [
    ("boulangerie", "boulangerie"),      # le titre
    ("Ibrahim", "boulangerie"),          # le pseudo
    ("quartier", "marche"),              # un mot-clé
    ("respiration", "nuit"),             # la transcription
    ("BOULANGERIE", "boulangerie"),      # la casse est ignorée
])
def test_la_recherche_trouve_par(client, corpus, requete, attendue):
    page = client.get("/", {"q": requete}).content.decode()
    assert str(corpus[attendue].uuid) in page
    for nom, capsule in corpus.items():
        if nom != attendue:
            assert str(capsule.uuid) not in page, f"« {requete} » ramène aussi {nom}"


@pytest.mark.django_db
def test_une_clameur_qui_correspond_deux_fois_n_apparait_qu_une_fois(client, corpus):
    """Deux mots-clés qui matchent, et la jointure la ramenait en double.
    / Two matching tags used to duplicate the row."""
    for nom in ("marché", "marchand"):
        tag = Tag.objects.create(nom=nom)
        TagDeCapsule.objects.create(
            capsule=corpus["marche"], tag=tag, origine=TagDeCapsule.MACHINE
        )

    page = client.get("/", {"q": "march"}).content.decode()
    assert page.count(f'id="clameur-{corpus["marche"].uuid}"') == 1


@pytest.mark.django_db
def test_une_recherche_sans_resultat_le_dit(client, corpus):
    page = client.get("/", {"q": "zzzzz"}).content.decode()
    for capsule in corpus.values():
        assert str(capsule.uuid) not in page
    assert "aucune" in page.lower()


@pytest.mark.django_db
def test_htmx_ne_recoit_que_la_liste_pas_la_page(client, corpus):
    """Le fragment remplace la liste ; renvoyer la page entière imbriquerait
    un second en-tête et un second champ de recherche dans le premier.
    / The fragment replaces the list; a full page would nest a second header."""
    entiere = client.get("/", {"q": "boulangerie"}).content.decode()
    fragment = client.get(
        "/", {"q": "boulangerie"}, headers={"HX-Request": "true"}
    ).content.decode()

    assert str(corpus["boulangerie"].uuid) in fragment
    assert "<html" not in fragment.lower()
    assert len(fragment) < len(entiere)


# --------------------------- ce que la page d'accueil porte autour
# Ces tests vivaient dans test_constellation.py, quand `/` etait le ciel.
# / Moved here when the home page became the list.

@pytest.mark.django_db
def test_la_page_rend_les_fiches_cote_serveur(client, corpus):
    """La liste est rendue par Django, et non construite en JavaScript : c'est
    la condition pour que HTMX puisse y remplacer une transcription par swap
    OOB quand elle arrive.
    / Server-rendered so HTMX has something to OOB-swap into."""
    reponse = client.get("/")
    assert reponse.status_code == 200
    contenu = reponse.content.decode()

    assert contenu.count('class="clameur"') == len(corpus)
    assert "lecteur-de-fiche" in contenu, "pas de lecteur audio dans les fiches"
    assert 'ws-connect="/ws/constellation"' in contenu, "pas de connexion temps réel"
    for capsule in corpus.values():
        assert f'id="transcription-{capsule.uuid}"' in contenu

@pytest.mark.django_db
def test_l_invitation_porte_le_qr_de_la_borne_active(client, corpus):
    """Un visiteur sur ordinateur ne peut pas enregistrer sur place : il lui
    faut son telephone, donc un QR.

    / A visitor on a desktop cannot record on the spot: they need their phone.
    """
    from django.core.cache import cache

    from bornes.models import Reglages

    cache.clear()
    assert Reglages.objects.filter(active=True).exists()
    contenu = client.get("/").content.decode()

    assert "Enregistrer une nouvelle clameur" in contenu
    assert "<svg" in contenu, "pas de QR dans l'invitation"
    # L'invitation vise l'adresse courte, pas le slug de la reglages : c'est elle
    # qu'on encode dans le QR et qu'on dit à voix haute.
    assert "/nouvelle" in contenu

@pytest.mark.django_db
def test_lieu_ferme_aucune_invitation_n_est_proposee(client, corpus):
    """Proposer d'enregistrer quand aucune reglages n'ecoute serait une promesse
    en l'air. / Offering to record with no open reglages would be an empty promise."""
    from django.core.cache import cache

    from bornes.models import Reglages

    reglages = Reglages.get_solo()
    reglages.active = False
    reglages.save()
    cache.clear()

    contenu = client.get("/").content.decode()
    assert "Enregistrer une nouvelle clameur" not in contenu

@pytest.mark.django_db
def test_l_adresse_courte_mene_a_la_page_d_enregistrement(client, corpus):
    """`/nouvelle` tient dans une phrase qu'on dit à voix haute, contrairement
    à `/b/<slug>`. C'est elle qu'on encode dans le QR."""
    from django.core.cache import cache

    cache.clear()
    reponse = client.get("/nouvelle")
    assert reponse.status_code == 200
    assert "Dépose une clameur" in reponse.content.decode()

    contenu = client.get("/").content.decode()
    assert 'href="/nouvelle"' in contenu, "l'invitation doit mener à l'adresse courte"
    assert "Enregistrer avec cet appareil" in contenu

@pytest.mark.django_db
def test_lieu_ferme_l_adresse_courte_explique(client, corpus):
    from django.core.cache import cache

    from bornes.models import Reglages

    reglages = Reglages.get_solo()
    reglages.active = False
    reglages.save()
    cache.clear()

    # La page reste accessible mais refuse les enregistrements : un visiteur
    # qui scanne un QR encore colle merite une explication, pas un 404.
    # / The page stays reachable and explains, rather than 404ing a live QR.
    contenu = client.get("/nouvelle").content.decode()
    assert "fermés" in contenu

@pytest.mark.django_db
def test_le_qr_porte_un_viewbox(client, corpus):
    """Segno n'en émet aucun : le canevas s'étirait sans que le dessin suive,
    et le code se retrouvait tassé dans un coin de la modale.
    / Segno emits none, so the drawing stayed put while the canvas stretched."""
    from django.core.cache import cache

    cache.clear()
    contenu = client.get("/").content.decode()
    assert 'class="segno"' in contenu
    debut = contenu.index('class="segno"') - 400
    assert "viewBox" in contenu[debut:debut + 500], "le QR ne se mettra pas à l'échelle"


@pytest.mark.django_db
def test_un_mot_cle_donne_par_l_auteur_et_par_la_machine_ne_s_affiche_qu_une_fois(
    client, reglages
):
    """L'auteur écrit « quartier », le modèle trouve « quartier » : la fiche
    affichait « · quartier · quartier ». Les deux origines restent distinctes
    en base — elles ne se mélangent jamais — mais la ligne qu'on lit, elle,
    ne répète pas.
    / Both origins stay separate in the database; the line we read does not
      repeat itself."""
    capsule = une_clameur(reglages, titre="Le marché")
    tag = Tag.objects.create(nom="quartier")
    TagDeCapsule.objects.create(capsule=capsule, tag=tag, origine=TagDeCapsule.AUTEUR)
    TagDeCapsule.objects.create(capsule=capsule, tag=tag, origine=TagDeCapsule.MACHINE)

    page = client.get("/").content.decode()
    assert page.count("· quartier") == 1


@pytest.mark.django_db
def test_une_recherche_sans_resultat_n_annonce_pas_un_site_vide(client, corpus):
    """La description de partage parle du CORPUS, pas de la recherche.

    Partagé tel quel, « /?q=zzzz » annonçait « Aucune clameur encore » alors
    que le site en porte cent : le lien disait au destinataire que le projet
    n'avait pas commencé.
    / Shared as-is, an empty search claimed the whole site was empty.
    """
    page = client.get("/", {"q": "zzzzz"}).content.decode()
    assert "Aucune clameur encore" not in page


@pytest.mark.django_db
def test_le_compteur_suit_la_recherche(client, corpus):
    """« 3 clameurs, à écouter » au-dessus d'un seul résultat : l'en-tête vit
    hors du fragment, HTMX ne le remplaçait donc jamais. Il voyage en swap
    OOB, comme les transcriptions.
    / The header lives outside the swapped fragment; it travels out-of-band."""
    fragment = client.get(
        "/", {"q": "boulangerie"}, headers={"HX-Request": "true"}
    ).content.decode()

    assert "hx-swap-oob" in fragment, "le compteur ne voyage pas avec les résultats"
    assert "1 clameur" in fragment or "Une clameur" in fragment


@pytest.mark.django_db
def test_aucun_commentaire_de_gabarit_ne_fuit_dans_la_page(client, corpus):
    """`{# … #}` NE PEUT PAS S'ÉTENDRE SUR PLUSIEURS LIGNES.

    Django cesse alors d'y voir un commentaire et le rend tel quel : nos notes
    de développement se retrouvaient dans la page, à la vue de tous. Sur
    plusieurs lignes, il faut `{% comment %}`.
    / Django only recognises single-line {# #}; a multi-line one is rendered
      verbatim into the page.
    """
    for adresse in ("/", "/?q=marché"):
        page = client.get(adresse).content.decode()
        assert "{#" not in page, f"un commentaire de gabarit sort en clair sur {adresse}"
        assert "{%" not in page, f"une balise de gabarit sort en clair sur {adresse}"


@pytest.mark.django_db
def test_le_compteur_n_apparait_qu_une_fois_au_chargement(client, corpus):
    """Le fragment de résultats porte le compteur en swap OOB, pour HTMX. Au
    chargement direct, la page inclut ce même fragment : le compteur sortait
    donc deux fois, une fois sous le titre et une fois sous la recherche.
    / The fragment carries the counter for HTMX; on a direct load the page
      includes that fragment too, and the counter appeared twice."""
    page = client.get("/").content.decode()
    assert page.count('id="compte"') == 1
