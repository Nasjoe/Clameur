"""Le recalcul du ciel : quand il part, quand il ne part pas.
/ The sky's recomputation: when it fires, and when it does not."""

from unittest.mock import patch

import numpy as np
import pytest
from django.core.cache import cache

from capsules.models import Capsule, Ciel, StatutCapsule
from capsules.tasks import VERROU_CIEL, programmer_le_recalcul, recalculer_le_ciel


def _six_clameurs(reglages):
    """Six clameurs aux vecteurs quelconques : de quoi faire tourner un calcul.
    / Six clameurs with arbitrary vectors: enough for one computation."""
    alea = np.random.default_rng(21)
    for _ in range(6):
        vecteur = alea.normal(0, 1, 1024)
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
            embedding=(vecteur / np.linalg.norm(vecteur)).tolist(),
        )


# ------------------------------------------------------------------ le verrou

@pytest.mark.django_db
def test_une_rafale_de_depots_ne_coute_qu_un_calcul():
    with patch.object(recalculer_le_ciel, "apply_async") as enfile:
        for _ in range(5):
            programmer_le_recalcul()

    assert enfile.call_count == 1


@pytest.mark.django_db
def test_la_tache_libere_le_verrou_des_son_depart(reglages):
    """Sans cela, une clameur déposée PENDANT le calcul ne programmerait rien
    et resterait sans étoile jusqu'au dépôt suivant — le défaut qui avait fait
    mettre le ciel en sommeil.

    ON REGARDE AU MILIEU DU CALCUL, pas à la fin : un `cache.delete` posé en
    dernière ligne satisferait une vérification finale tout en laissant le
    verrou en place pendant les vingt secondes qui comptent.
    / Checked mid-computation: a delete on the last line would fool a final check.
    """
    from capsules import ciel

    _six_clameurs(reglages)
    cache.set(VERROU_CIEL, 1, 120)
    verrou_pendant_le_calcul = []

    # LA VRAIE FONCTION EST CAPTUREE AVANT LE PATCH. L'appeler par son nom de
    # module depuis l'espion appellerait le mock, qui rappellerait l'espion :
    # récursion infinie, et le test ne dit plus rien du verrou.
    # / Captured before patching: calling it by name would call the mock itself.
    vraie_densite = ciel.densite

    def _espionner(positions):
        verrou_pendant_le_calcul.append(cache.get(VERROU_CIEL))
        return vraie_densite(positions)

    with patch("capsules.ciel.densite", side_effect=_espionner):
        recalculer_le_ciel()

    assert verrou_pendant_le_calcul == [None], "le verrou tient encore pendant le calcul"


@pytest.mark.django_db(transaction=True)
def test_le_calcul_verrouille_le_ciel_contre_l_autre_worker(reglages):
    """La production tourne à `--concurrency=2` : deux recalculs peuvent partir
    ensemble.

    ON LIT LE SQL RÉELLEMENT ENVOYÉ, et non un appel de méthode : un
    `select_for_update()` dont la requête n'est jamais évaluée ne verrouille
    rien, et un mock d'appel le laisserait passer.
    / We read the SQL actually sent: an unevaluated select_for_update locks nothing.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _six_clameurs(reglages)

    with CaptureQueriesContext(connection) as requetes:
        recalculer_le_ciel()

    assert any("FOR UPDATE" in requete["sql"] for requete in requetes), (
        "aucune requête ne verrouille le ciel : deux workers peuvent le calculer ensemble"
    )


@pytest.mark.django_db
def test_le_cache_indisponible_n_empeche_pas_d_enfiler():
    with patch("capsules.tasks.cache.add", side_effect=RuntimeError("redis mort")), \
         patch.object(recalculer_le_ciel, "apply_async") as enfile:
        programmer_le_recalcul()

    assert enfile.call_count == 1


@pytest.mark.django_db
def test_redis_mort_le_retrait_passe_quand_meme(admin_client, capsule_publiee):
    """Le retrait LCEN ne dépend de rien.

    ON PASSE PAR LA VRAIE VUE : c'est elle qui doit survivre à un courtier
    mort, et un appel direct à `programmer_le_recalcul()` ne prouverait rien
    sur le chemin qu'emprunte un auteur pressé de se taire.
    / Through the real view: that is the path a takedown actually takes.
    """
    with patch("capsules.tasks.recalculer_le_ciel.apply_async",
               side_effect=RuntimeError("redis mort")):
        reponse = admin_client.post(f"/c/{capsule_publiee.uuid}/retirer")

    assert reponse.status_code in (302, 303)
    capsule_publiee.refresh_from_db()
    assert capsule_publiee.statut == StatutCapsule.RETIREE


# ------------------------------------------------------------- ce qui se calcule

@pytest.mark.django_db
def test_le_tsne_ne_tourne_pas_quand_rien_n_attend_de_position(reglages):
    """Un retrait ne doit relancer que la densité et les régions : rien ne
    s'ajoute, la projection n'a aucune raison de tourner — et si elle tournait,
    toutes les étoiles se déplaceraient sous les yeux des visiteurs.
    / A takedown adds nothing: projecting again would move every star.
    """
    _six_clameurs(reglages)
    recalculer_le_ciel()          # premier calcul : projette
    avant = {c.uuid: (c.position_x, c.position_y) for c in Capsule.objects.all()}

    with patch("capsules.ciel.projeter") as projection:
        recalculer_le_ciel()      # second : rien n'attend de position

    projection.assert_not_called()
    apres = {c.uuid: (c.position_x, c.position_y) for c in Capsule.objects.all()}
    assert avant == apres
    assert Ciel.get_solo().grille, "la densité, elle, doit avoir été recalculée"


@pytest.mark.django_db
def test_un_vecteur_inexploitable_ne_relance_pas_la_projection_a_vie(reglages):
    """Sinon la règle « projeter s'il manque une position » ne termine jamais :
    la capsule abîmée n'en reçoit pas, et rappelle le t-SNE à chaque calcul.
    / Otherwise "project if a position is missing" never terminates.
    """
    alea = np.random.default_rng(12)
    for numero in range(6):
        vecteur = [0.0] * 1024 if numero == 0 else list(alea.normal(0, 1, 1024))
        Capsule.objects.create(
            reglages=reglages, statut=StatutCapsule.PUBLIEE,
            duree_secondes=30, embedding=vecteur,
        )
    recalculer_le_ciel()

    with patch("capsules.ciel.projeter") as projection:
        recalculer_le_ciel()

    projection.assert_not_called()
    assert Capsule.objects.filter(erreur_enrichissement__icontains="vecteur").exists(), (
        "la capsule au vecteur nul doit être signalée à l'opérateur"
    )


@pytest.mark.django_db
def test_moins_de_trois_clameurs_ecrit_un_ciel_vide(reglages):
    """Un relief périmé sur un corpus qui n'existe plus serait pire que rien.
    / A stale relief over a corpus that no longer exists is worse than nothing."""
    alea = np.random.default_rng(13)
    # ELLE PORTE DEJA UNE POSITION, d'un calcul precedent : sans cela,
    # l'assertion « plus aucune position » serait vraie avant meme l'appel.
    Capsule.objects.create(
        reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
        embedding=list(alea.normal(0, 1, 1024)), position_x=0.5, position_y=0.5,
    )
    ciel_perime = Ciel.get_solo()
    ciel_perime.grille, ciel_perime.regions = [[1.0]], [{"nom": "vieux"}]
    ciel_perime.save()

    recalculer_le_ciel()

    objet = Ciel.get_solo()
    assert objet.grille == [] and objet.regions == []
    assert not Capsule.objects.exclude(position_x=None).exists()


# ------------------------------------------------- le rattrapage des vecteurs

def _une_clameur_sans_vecteur(reglages, texte="On parlait du marché du mercredi."):
    return Capsule.objects.create(
        reglages=reglages, statut=StatutCapsule.PUBLIEE, duree_secondes=30,
        transcription_texte=texte,
    )


@pytest.mark.django_db
def test_sans_option_la_commande_annonce_les_vecteurs_manquants_sans_rien_enfiler(reglages):
    """Un vecteur coûte un appel payant : cent tâches ne partent pas sur un
    malentendu. Par défaut la commande compte, le dit, et ne touche à rien.
    / A vector costs a paid call: by default the command only counts and says so.
    """
    from io import StringIO

    from django.core.management import call_command

    _une_clameur_sans_vecteur(reglages)
    sortie = StringIO()

    with patch("capsules.tasks.embarquer.delay") as enfile:
        call_command("projeter_la_constellation", stdout=sortie)

    enfile.assert_not_called()
    assert "attend son vecteur" in sortie.getvalue()


@pytest.mark.django_db
def test_avec_rattraper_une_tache_part_par_clameur_qui_a_une_transcription(reglages):
    """Et AUCUNE pour celle qui n'en a pas : `embarquer` rendrait « rien à
    embarquer », et une tâche pour rien encombre la file sans rien réparer.
    / None for a clameur with no transcription: the task would do nothing.
    """
    from io import StringIO

    from django.core.management import call_command

    parlante = _une_clameur_sans_vecteur(reglages)
    _une_clameur_sans_vecteur(reglages, texte="")     # jamais transcrite

    with patch("capsules.tasks.embarquer.delay") as enfile:
        call_command("projeter_la_constellation", rattraper=True, stdout=StringIO())

    assert enfile.call_count == 1
    assert enfile.call_args[0][0] == str(parlante.uuid)


@pytest.mark.django_db
def test_le_rattrapage_survit_a_un_courtier_mort(reglages):
    """Redis mort, la commande le journalise et va au bout : elle ne doit pas
    s'arrêter à la première clameur et laisser le reste sans vecteur.
    / A dead broker must not stop the catch-up at the first clameur.
    """
    from io import StringIO

    from django.core.management import call_command

    for _ in range(3):
        _une_clameur_sans_vecteur(reglages)

    with patch("capsules.tasks.embarquer.delay", side_effect=RuntimeError("redis mort")):
        call_command("projeter_la_constellation", rattraper=True, stdout=StringIO())


# ------------------------------------------------------------ les déclencheurs

@pytest.mark.django_db
def test_l_action_d_admin_retirer_programme_un_recalcul(admin_client, capsule_publiee):
    """Les actions d'admin passent par `queryset.update()`, qui n'émet aucun
    signal : sans appel explicite, une clameur retirée resterait au ciel.
    / Admin actions use queryset.update(): no signal, so the call must be explicit.
    """
    with patch("capsules.admin.programmer_le_recalcul") as programme:
        admin_client.post(
            "/admin/capsules/capsule/",
            {"action": "retirer", "_selected_action": [str(capsule_publiee.uuid)]},
            follow=True,
        )

    programme.assert_called_once()
