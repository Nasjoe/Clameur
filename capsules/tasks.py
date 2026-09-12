"""Enrichissement semantique. Toujours facultatif, jamais bloquant.
/ Semantic enrichment: always optional, never blocking."""

import json
import logging
import os

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from capsules.diffusion import diffuser_la_transcription
from capsules.models import Capsule, StatutCapsule, Tag, TagDeCapsule
from capsules.transcription import transcrire_le_fichier

logger = logging.getLogger(__name__)

NOMBRE_DE_TAGS_MACHINE = 3
MOTS_DU_TITRE = 6

# LES TROIS ETAPES PARTAGENT UN SEUL CHAMP D'ERREUR, et le nom de l'etape est
# ce qui permet de savoir a laquelle appartient le message qui s'y trouve. Ce
# ne sont donc pas des libelles d'affichage : ce sont des cles, et c'est
# pourquoi elles vivent ici plutot qu'en toutes lettres a l'appel.
# / One error field for three steps: the step name is the key that says whose
#   message it holds.
ETAPE_TRANSCRIPTION = "Transcription"
ETAPE_TAGS = "Extraction des tags"
ETAPE_EMBEDDING = "Embedding"

VERROU_CIEL = "ciel:programme"

# DEUX MINUTES. Assez pour qu'une rafale de depots ne coute qu'un calcul et que
# les tags machine soient arrives, assez peu pour qu'une clameur neuve trouve
# son etoile avant que son auteur ne referme la page.
# / Two minutes: one computation per burst, and a fresh star before the visitor
#   closes the page.
DELAI_RECALCUL = 120


def _enfiler(tache, uuid_capsule: str) -> None:
    """Enfile une suite sans laisser son echec remonter.
    / Queues a follow-up without letting its failure bubble up."""
    try:
        tache.delay(uuid_capsule)
    except Exception:
        logger.exception("enqueue de %s impossible pour %s", tache.name, uuid_capsule)


def _noter_l_echec(capsule, etape: str, erreur: Exception) -> None:
    """Une panne de Mistral ne depublie JAMAIS une capsule : elle la prive
    seulement de sa transcription. / A Mistral outage never unpublishes."""
    logger.exception("%s impossible pour %s", etape, capsule.uuid)
    capsule.erreur_enrichissement = f"{etape} : {erreur}"
    capsule.save(update_fields=["erreur_enrichissement"])


def _effacer_l_echec(capsule, etape: str) -> None:
    """Efface l'erreur de CETTE etape, et d'elle seule.

    L'OPERATEUR REJOUE UNE ETAPE, ELLE REUSSIT, ET LA CAPSULE ANNONCAIT
    TOUJOURS UN ECHEC : il ne pouvait plus distinguer ce qui etait repare de ce
    qui ne l'etait pas.
    Mais effacer sans regarder serait pire. Les trois etapes se partagent un
    seul champ, et `taguer` et `embarquer` courent EN PARALLELE : la reussite
    de l'une ferait disparaitre l'echec de l'autre — une clameur sans etoile,
    et plus rien pour dire pourquoi. On ne retire donc que ce que l'on a
    soi-meme ecrit.
    / A blind wipe would hide the concurrent step's failure: only clear what
      this step itself wrote.
    """
    if not (capsule.erreur_enrichissement or "").startswith(etape):
        return
    capsule.erreur_enrichissement = ""
    capsule.save(update_fields=["erreur_enrichissement"])


@shared_task
def transcrire(uuid_capsule: str) -> str:
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    try:
        resultat = transcrire_le_fichier(capsule.audio_a_servir.path)
    except Exception as erreur:
        _noter_l_echec(capsule, ETAPE_TRANSCRIPTION, erreur)
        return "echec"

    capsule.transcription_raw = {"segments": resultat["segments"]}
    capsule.transcription_texte = resultat["texte"]
    capsule.langue_detectee = resultat["langue"]

    # ICI ON EFFACE TOUT, SANS REGARDER — a la difference de `taguer` et
    # `embarquer`, qui ne retirent que leur propre message. C'est la tete de
    # la chaine : une transcription reussie relance les deux suites derriere
    # elle, et l'etat des etapes precedentes n'a plus cours.
    # / The head of the chain restarts both follow-ups, so the previous state
    #   no longer applies.
    capsule.erreur_enrichissement = ""

    # `update_fields` N'EST PAS UNE OPTIMISATION ICI, C'EST UNE CORRECTION.
    # L'instance a ete chargee avant l'appel a Voxtral, qui dure de dix
    # secondes a une minute. Un `save()` complet reecrirait l'etat d'alors :
    # une capsule retiree entre-temps par l'operateur redeviendrait publiee —
    # le retrait LCEN annule sans trace — et les ecoutes comptees pendant
    # l'appel seraient perdues.
    # / Not an optimisation: a full save would resurrect a capsule the operator
    #   withdrew during the call, and lose the plays counted meanwhile.
    capsule.save(update_fields=[
        "transcription_raw", "transcription_texte",
        "langue_detectee", "erreur_enrichissement",
    ])

    # DIFFERE AU COMMIT : diffuser avant que la transaction soit ecrite
    # enverrait un texte que la base ne contient pas encore. En cas de
    # rollback, la page afficherait une transcription qui n'existe pas.
    # / Deferred to commit: broadcasting earlier could push uncommitted text.
    transaction.on_commit(lambda: diffuser_la_transcription(capsule))

    # DEUX SUITES EN PARALLELE : le titre et les mots-cles d'un cote, le
    # vecteur de l'autre. Elles ne se parlent pas et ne s'attendent pas ; c'est
    # pourquoi chacune ne retire du champ d'erreur partage que le message
    # qu'elle y a elle-meme ecrit.
    # / Two follow-ups in parallel; each only clears its own error message.
    _enfiler(taguer, uuid_capsule)
    _enfiler(embarquer, uuid_capsule)
    return "ok"


def _appeler_le_modele(texte: str) -> tuple[str, list[str]]:
    """Demande un titre et des mots-clés au modèle. Rend (titre, mots).

    UN SEUL APPEL POUR LES DEUX. Le titre se déduit de la même transcription
    que les mots-clés, par le même modèle : en demander un second coûterait
    une requête et une attente de plus pour un texte de six mots.
    / One call for both: a second request for six words would be waste.

    LE MODELE ENTOURE SOUVENT SON JSON DE BALISES DE CODE, même quand on lui
    demande de n'en pas mettre. Sans ce nettoyage, `json.loads` lève et la
    capsule perd ses mots-clés sur une question de mise en forme.
    / Models often fence their JSON even when told not to.

    ET IL REPOND UN OBJET, JAMAIS LE TABLEAU DEMANDE. Relevé sur une vraie
    capsule le 2026-08-31, trois fois sur trois :

        {"mots-clés": ["boulangerie", "fermeture", "nostalgie"]}

    Itérer sur ce dictionnaire donne ses CLÉS. Chaque capsule recevait donc un
    unique tag machine nommé « mots-clés » à la place de ses vrais mots-clés —
    sans erreur, sans trace : `taguer` rendait « ok ». Le mock de la suite de
    tests, lui, rendait sagement un tableau, et cachait le défaut.
    On demande donc un objet, ET on accepte les deux formes : la panne était
    silencieuse, elle mérite deux filets.
    / The model returns an object whose keys we were iterating over; we now ask
      for an object and accept both shapes.
    """
    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    reponse = client.chat.complete(
        model=settings.MISTRAL_MODELE_TAGS,
        messages=[
            {
                "role": "user",
                "content": (
                    "Voici un témoignage enregistré dans la rue. Donne-lui un "
                    f"titre court — {MOTS_DU_TITRE} mots au plus, sans point "
                    "final — et exactement "
                    f"{NOMBRE_DE_TAGS_MACHINE} mots-clés, le tout en français. "
                    'Réponds uniquement par un objet JSON de la forme '
                    '{"titre": "…", "tags": ["…"]}, sans commentaire.'
                    "\n\n"
                    f"{texte[:4000]}"
                ),
            }
        ],
        response_format={"type": "json_object"},
    )
    brut = (reponse.choices[0].message.content or "").strip()
    if brut.startswith("```"):
        brut = brut.split("```")[1] if "```" in brut[3:] else brut[3:]
        brut = brut.removeprefix("json").strip()
    valeur = json.loads(brut)
    titre = ""
    if isinstance(valeur, dict):
        # La premiere valeur qui est une liste, quel que soit le nom de la cle :
        # le modele l'appelle tantot « tags », tantot « mots-clés », tantot
        # « mots_clés ». Le titre, lui, est la premiere chaine.
        # / Whatever the keys are called.
        titre = next((v for v in valeur.values() if isinstance(v, str)), "")
        valeur = next((v for v in valeur.values() if isinstance(v, list)), [])
    elif not isinstance(valeur, list):
        valeur = []

    if not valeur:
        # ON LEVE, ON NE REND PAS UNE LISTE VIDE. Rendre [] ferait dire « ok »
        # a la tache et laisserait la capsule sans mots-cles, sans erreur et
        # sans trace — exactement la panne silencieuse qu'on vient de corriger.
        # Levee, l'erreur s'inscrit dans `erreur_enrichissement`, se voit dans
        # la console et se rejoue.
        # / Raise, never return an empty list: that was the silent failure.
        raise ValueError(f"aucun mot-clé dans la réponse du modèle : {brut[:200]}")
    # LE TITRE EST UN CONFORT, LES MOTS-CLES SONT LA MATIERE DE LA RECHERCHE.
    # Un titre manquant ne doit pas emporter les mots-cles avec lui : la fiche
    # retombe alors sur le pseudo, et rien n'est perdu.
    # / A missing title must not take the keywords down with it.
    return str(titre).strip()[:120], [str(mot) for mot in valeur]


@shared_task
def taguer(uuid_capsule: str) -> str:
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    if not capsule.transcription_texte:
        return "rien a taguer"

    try:
        titre, mots = _appeler_le_modele(capsule.transcription_texte)
    except Exception as erreur:
        _noter_l_echec(capsule, ETAPE_TAGS, erreur)
        return "echec"

    if titre:
        # `update_fields`, pour la meme raison que dans `transcrire` : l'appel
        # a dure, et un save complet reecrirait un etat perime.
        # / update_fields: the call took time, a full save would rewrite stale state.
        capsule.titre = titre
        capsule.save(update_fields=["titre"])

    for mot in [str(m).strip().lower()[:60] for m in mots][:NOMBRE_DE_TAGS_MACHINE]:
        if not mot:
            continue
        tag, _cree = Tag.objects.get_or_create(nom=mot)
        # Les tags de la machine ne se melangent jamais a ceux de l'auteur.
        # / Machine tags never blend into the author's own words.
        TagDeCapsule.objects.get_or_create(
            capsule=capsule, tag=tag, origine=TagDeCapsule.MACHINE
        )

    _effacer_l_echec(capsule, ETAPE_TAGS)
    # Les mots-cles nomment les regions du ciel : de nouveaux tags peuvent
    # renommer un massif. / Keywords name the sky's regions.
    programmer_le_recalcul()
    return "ok"


def _calculer_le_vecteur(texte: str) -> list[float]:
    """Rend le vecteur du texte, tel que le modèle le produit.
    / Returns the text's vector, as produced by the model."""
    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    reponse = client.embeddings.create(
        model=settings.MISTRAL_MODELE_EMBEDDING, inputs=[texte[:8000]]
    )
    return reponse.data[0].embedding


@shared_task
def embarquer(uuid_capsule: str) -> str:
    """Calcule le vecteur qui place la clameur dans la constellation.
    / Computes the vector that places the clameur in the constellation."""
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    if not capsule.transcription_texte:
        return "rien a embarquer"

    try:
        vecteur = _calculer_le_vecteur(capsule.transcription_texte)
    except Exception as erreur:
        _noter_l_echec(capsule, ETAPE_EMBEDDING, erreur)
        return "echec"

    attendu = settings.MISTRAL_DIMENSIONS_EMBEDDING
    if len(vecteur) != attendu:
        # Un vecteur tronque entrerait en base et fausserait la projection
        # entiere sans que rien ne le signale.
        # / A truncated vector would silently skew the whole projection.
        _noter_l_echec(
            capsule, ETAPE_EMBEDDING,
            ValueError(f"{len(vecteur)} dimensions au lieu de {attendu}"),
        )
        return "echec"

    capsule.embedding = vecteur
    capsule.enrichie_le = timezone.now()
    capsule.save(update_fields=["embedding", "enrichie_le"])
    _effacer_l_echec(capsule, ETAPE_EMBEDDING)
    # Une clameur de plus a projeter : c'est ce qui lui donnera son etoile.
    # / One more clameur to project: this is what earns it a star.
    programmer_le_recalcul()
    return "ok"


def programmer_le_recalcul() -> None:
    """Programme un recalcul du ciel, au plus un par fenetre.

    N'ECHOUE JAMAIS. Elle est appelee depuis le retrait d'une clameur, qui est
    une obligation legale : ni un cache muet ni un courtier mort ne doivent
    empecher un auteur de faire taire sa voix.
    / Never fails: it is called from the LCEN takedown path.
    """
    try:
        if not cache.add(VERROU_CIEL, 1, DELAI_RECALCUL):
            return
    except Exception:
        logger.warning("cache indisponible : recalcul du ciel enfilé sans verrou")

    try:
        recalculer_le_ciel.apply_async(countdown=DELAI_RECALCUL)
    except Exception:
        logger.exception("enqueue du recalcul du ciel impossible")


@shared_task
def recalculer_le_ciel() -> str:
    """Recalcule les positions, le relief et les regions.

    SANS ARGUMENT, donc toujours a partir de l'etat frais : la tache est
    idempotente, ce qu'exige `acks_late`.
    / No argument: always recomputed from fresh state, as acks_late demands.
    """
    # LE VERROU TOMBE EN PREMIER. Une clameur deposee pendant le calcul doit
    # pouvoir programmer le suivant ; sinon elle attend un depot de plus pour
    # exister — le defaut meme qui avait fait mettre le ciel en sommeil.
    # / Released first: a clameur arriving mid-computation must re-arm.
    try:
        cache.delete(VERROU_CIEL)
    except Exception:
        logger.warning("cache indisponible : verrou du ciel non libéré")

    # Import paresseux : `tasks` est importe par `publication`, et numpy n'a
    # rien a faire dans un worker web. / Lazy: numpy has no place in a web worker.
    import numpy as np

    from capsules import ciel as calcul
    from capsules.models import Ciel

    with transaction.atomic():
        # `get_solo()` d'abord : on ne verrouille pas une ligne qui n'existe pas.
        # / get_solo() first: there is no row to lock before the first run.
        objet = Ciel.get_solo()
        Ciel.objects.select_for_update().filter(pk=objet.pk).first()

        capsules = list(
            Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
            .exclude(embedding=None)
            .prefetch_related("tags_de_capsule__tag")
        )
        if capsules:
            vecteurs = np.vstack([np.asarray(c.embedding, dtype=float) for c in capsules])
            exploitables = np.isfinite(vecteurs).all(axis=1) & (
                np.linalg.norm(vecteurs, axis=1) > 0
            )
        else:
            vecteurs = np.empty((0, 0))
            exploitables = np.zeros(0, dtype=bool)

        # UN VECTEUR ABIME EST SIGNALE DANS L'ADMIN. C'est le masque
        # `exploitables` qui l'ecarte du calcul, juste au-dessus ; ce message
        # existe pour que l'operateur sache pourquoi cette clameur n'a pas
        # d'etoile, au lieu de la chercher en vain dans le ciel.
        # / The mask already excludes it; this message tells the operator why.
        for capsule, garde in zip(capsules, exploitables):
            if not garde and "vecteur" not in capsule.erreur_enrichissement:
                _noter_l_echec(
                    capsule, ETAPE_EMBEDDING,
                    ValueError("vecteur inexploitable, pas d'étoile"),
                )

        retenues = [c for c, garde in zip(capsules, exploitables) if garde]
        vecteurs = vecteurs[exploitables] if len(capsules) else vecteurs

        if len(retenues) < 3:
            Capsule.objects.exclude(position_x=None).update(position_x=None, position_y=None)
            objet.grille, objet.regions = [], []
            objet.calcule_le = timezone.now()
            objet.save(update_fields=["grille", "regions", "calcule_le"])
            return "trop peu"

        # LE T-SNE NE TOURNE QUE SI QUELQUE CHOSE ATTEND UNE POSITION. Un
        # retrait ne fait rien entrer : recalculer la projection deplacerait
        # toutes les etoiles pour rien. / Only project when a star is missing.
        if any(c.position_x is None for c in retenues):
            positions = calcul.projeter(vecteurs)
            for capsule, (x, y) in zip(retenues, positions):
                capsule.position_x, capsule.position_y = float(x), float(y)
            Capsule.objects.bulk_update(
                retenues, ["position_x", "position_y"], batch_size=200
            )
        else:
            positions = np.array([[c.position_x, c.position_y] for c in retenues])

        grille = calcul.densite(positions)
        if not np.isfinite(grille).all():
            # SEULE BARRIERE CONTRE LE NAN : `json_script` le serialise tel
            # quel, et `JSON.parse` casse alors sans un mot dans la console.
            # / json_script emits NaN verbatim and JSON.parse dies silently.
            logger.error("grille non finie : ciel laissé vide")
            objet.grille, objet.regions = [], []
        else:
            tags = [
                [(lien.tag.nom, lien.origine) for lien in c.tags_de_capsule.all()]
                for c in retenues
            ]
            objet.grille = np.round(grille, 3).tolist()
            objet.regions = calcul.regions(grille, positions, tags)

        # Les positions des capsules qui ne sont plus projetees disparaissent :
        # une retiree republiee ne doit pas revenir a la place d'une projection
        # d'avant. / Stale positions go, or a republished capsule lands wrong.
        Capsule.objects.exclude(
            uuid__in=[c.uuid for c in retenues]
        ).exclude(position_x=None).update(position_x=None, position_y=None)

        objet.calcule_le = timezone.now()
        objet.save(update_fields=["grille", "regions", "calcule_le"])

    return "ok"
