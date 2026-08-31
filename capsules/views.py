"""Vues de la borne et de la lecture. / Borne and playback views."""

import logging
import math

import segno
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db.models import F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from bornes.models import Borne
from capsules.garde_fous import limite_atteinte
from capsules.models import Capsule, StatutCapsule, Tag, TagDeCapsule
from capsules.photos import purger_les_exif
from capsules.publication import publier

logger = logging.getLogger(__name__)

DUREE_DU_CACHE_IMPRIMANTE = 30
NOMBRE_MAX_DE_TAGS = 2

# Au-dela, le ciel devient illisible et la page trop lourde. La
# constellation n'est pas un moteur de recherche : c'est une vue d'ensemble.
# / Beyond this the sky is unreadable; it is an overview, not a search engine.
PLAFOND_CONSTELLATION = 600

# Le QR d'invitation ne change que si la borne change : inutile de le
# regenerer pour chaque visiteur.
# / The invitation QR only changes with the borne.
DUREE_DU_CACHE_INVITATION = 600

# Une couleur par LOCUTEUR, pas par segment. Colorer au fil des segments
# donnerait deux teintes differentes a la meme personne qui parle deux fois :
# la transcription deviendrait illisible au lieu d'aider.
# / One colour per speaker, not per segment.
COULEURS_DES_VOIX = [
    "oklch(0.73 0.15 38)",   # terracotta
    "oklch(0.83 0.13 78)",   # ambre
    "oklch(0.76 0.13 12)",   # rose
    "oklch(0.80 0.11 55)",   # abricot
    "oklch(0.70 0.12 25)",   # brique
    "oklch(0.86 0.10 95)",   # ble
    "oklch(0.74 0.14 350)",  # framboise
    "oklch(0.78 0.10 65)",   # sable dore
]


def interroger_l_imprimante(borne) -> dict:
    """Etat de l'imprimante, mis en cache 30 secondes.

    Sans ce cache, chaque visiteur qui ouvre la page declencherait un appel a
    l'API Sunmi. / Without this cache every visitor would hit the Sunmi API.
    """
    cle = f"imprimante:{borne.slug}"
    etat = cache.get(cle)
    if etat is not None:
        return etat

    from impression.tasks import choisir_le_backend

    backend = choisir_le_backend(borne)
    if hasattr(backend, "est_en_ligne"):
        en_ligne, message = backend.est_en_ligne()
    else:
        en_ligne, message = backend.can_print()

    etat = {"en_ligne": en_ligne, "message": message}
    cache.set(cle, etat, DUREE_DU_CACHE_IMPRIMANTE)
    return etat


@require_GET
def accueil_borne(request, slug):
    borne = get_object_or_404(Borne, slug=slug)
    return render(
        request,
        "capsules/borne.html",
        {
            "borne": borne,
            "imprimante": interroger_l_imprimante(borne),
            "nombre_max_de_tags": NOMBRE_MAX_DE_TAGS,
        },
    )


@require_POST
def creer_capsule(request, slug):
    """Recoit l'audio des l'arret de l'enregistrement.

    L'envoi a lieu AVANT la saisie du pseudo : cela met a profit le temps de
    frappe et garantit qu'un audio n'est jamais perdu si l'onglet se ferme.
    / Uploaded before the form is filled: the audio is never lost.
    """
    borne = get_object_or_404(Borne, slug=slug)
    if not borne.active:
        return JsonResponse({"erreur": _("Cette borne est fermée.")}, status=403)

    if limite_atteinte(request, "creation"):
        return JsonResponse(
            {"erreur": _("Trop d'enregistrements depuis cet appareil.")}, status=429
        )

    fichier = request.FILES.get("audio")
    if not fichier:
        return JsonResponse({"erreur": _("Aucun audio reçu.")}, status=400)

    # AUCUNE LISTE BLANCHE DE FORMAT. Chrome envoie du webm/opus, iOS du
    # mp4/aac, Firefox de l'ogg/opus, et demain autre chose. Filtrer sur une
    # liste rejetterait un navigateur minoritaire sans que personne s'en
    # apercoive. / No format whitelist: it would silently reject a browser.
    capsule = Capsule.objects.create(
        borne=borne,
        audio_original=fichier,
        duree_secondes=int(float(request.POST.get("duree", 0) or 0)),
    )
    return JsonResponse({"uuid": str(capsule.uuid)})


@require_POST
def publier_capsule(request, uuid):
    capsule = get_object_or_404(Capsule, uuid=uuid)
    if capsule.statut != StatutCapsule.BROUILLON:
        return JsonResponse({"erreur": _("Capsule déjà publiée.")}, status=409)

    if limite_atteinte(request, "publication"):
        return JsonResponse({"erreur": _("Trop de publications.")}, status=429)

    capsule.pseudo = (request.POST.get("pseudo") or "").strip()[:80]

    photo = request.FILES.get("photo")
    if photo:
        try:
            capsule.photo.save(f"{capsule.uuid}.jpg", purger_les_exif(photo), save=False)
        except Exception:
            # Une photo illisible ne doit pas empecher de publier la voix.
            # / An unreadable photo must not block publishing the voice.
            logger.exception("photo inutilisable pour %s", capsule.uuid)

    _attacher_les_tags(capsule, request.POST.getlist("tags"))
    publier(capsule)

    return JsonResponse({"uuid": str(capsule.uuid), "url": f"/c/{capsule.uuid}"})


def _attacher_les_tags(capsule, mots) -> None:
    for mot in [m.strip().lower()[:60] for m in mots if m.strip()][:NOMBRE_MAX_DE_TAGS]:
        tag, _cree = Tag.objects.get_or_create(nom=mot)
        TagDeCapsule.objects.get_or_create(
            capsule=capsule, tag=tag, origine=TagDeCapsule.AUTEUR
        )


@require_GET
def lire_capsule(request, uuid):
    capsule = get_object_or_404(
        Capsule.objects.select_related("borne").prefetch_related("tags_de_capsule__tag"),
        uuid=uuid,
    )

    # Un brouillon n'a jamais eu de ticket : il n'existe pas publiquement.
    # / A draft never had a ticket: it does not exist publicly.
    if capsule.statut == StatutCapsule.BROUILLON:
        raise Http404

    # Une capsule retiree, elle, a son ticket colle quelque part dans la rue.
    # Son porteur merite une explication, jamais un 404 nu.
    # / A withdrawn capsule has a ticket out there: explain, never a bare 404.
    if capsule.statut == StatutCapsule.RETIREE:
        return render(request, "capsules/capsule_retiree.html", {"capsule": capsule}, status=200)

    return render(
        request,
        "capsules/capsule.html",
        {
            "capsule": capsule,
            "segments": _colorer_les_voix(
                (capsule.transcription_raw or {}).get("segments") or []
            ),
            "tags": [lien.tag.nom for lien in capsule.tags_de_capsule.all()],
        },
    )


def _colorer_les_voix(segments):
    """Attribue une couleur a chaque locuteur, dans son ordre d'apparition.
    / Assigns a colour to each speaker, in order of first appearance."""
    couleur_du_locuteur = {}
    for segment in segments:
        locuteur = segment.get("speaker") or "voix"
        if locuteur not in couleur_du_locuteur:
            couleur_du_locuteur[locuteur] = COULEURS_DES_VOIX[
                len(couleur_du_locuteur) % len(COULEURS_DES_VOIX)
            ]
        segment["couleur"] = couleur_du_locuteur[locuteur]
    return segments


@require_POST
def compter_une_ecoute(request, uuid):
    """Appele AU CLIC PLAY, jamais au chargement de la page.

    C'est la seule mesure qui repondra a la question dont depend le projet :
    est-ce que les passants ecoutent vraiment ?
    / Called on play, never on page load: the only metric that matters.
    """
    Capsule.objects.filter(uuid=uuid, statut=StatutCapsule.PUBLIEE).update(
        nombre_ecoutes=F("nombre_ecoutes") + 1
    )
    return HttpResponse(status=204)


@staff_member_required
@require_GET
def affiche_borne(request, slug):
    """L'affiche A4 a coller au mur, avec le QR d'entree de la borne.

    C'est le seul objet du projet que personne d'autre ne peut fabriquer, et
    sans lui la borne n'existe pas : le QR est le seul chemin entre le mur et
    le telephone du visiteur.
    / The poster is the only path from the wall to the visitor's phone.
    """
    borne = get_object_or_404(Borne, slug=slug)
    url_entree = f"{settings.URL_PUBLIQUE.rstrip('/')}{reverse('capsules:accueil_borne', args=[borne.slug])}"

    # Correction d'erreur haute : une affiche vit dehors, elle se salit, se
    # dechire, prend la pluie. Le niveau H tolere 30 % du code abime.
    # / High error correction: a poster gets dirty, torn and rained on.
    qr = segno.make(url_entree, error="h")

    return render(
        request,
        "capsules/affiche.html",
        {
            "borne": borne,
            "url_entree": url_entree,
            "qr_svg": qr.svg_inline(scale=12, border=0, dark="#0b0d14"),
        },
    )


@require_GET
def constellation(request):
    """Les deux ecrans : la liste et le ciel, synchronises.

    LA LISTE EST RENDUE PAR DJANGO, et non construite en JavaScript. C'est ce
    qui permet a HTMX de remplacer une transcription par swap OOB quand elle
    arrive : on ne peut pas viser un element que le serveur n'a jamais rendu.
    / Django renders the list so HTMX can OOB-swap into it later.

    TOUT EST CHARGE D'UN COUP, sans pagination : la synchronisation suppose que
    n'importe quelle pastille trouve son element dans la liste.
    / No pagination: any star must find its card.
    """
    capsules = (
        Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
        .exclude(position_x=None)
        .prefetch_related("tags_de_capsule__tag")
        .order_by("-publiee_le")[:PLAFOND_CONSTELLATION]
    )
    return render(
        request,
        "capsules/constellation.html",
        {
            "clameurs": [decrire_une_clameur(capsule) for capsule in capsules],
            "nombre": len(capsules),
            "invitation": invitation_a_enregistrer(request),
        },
    )


def invitation_a_enregistrer(request) -> dict | None:
    """Le QR a scanner pour deposer une clameur, ou None s'il n'y a pas de borne.

    On vise la premiere borne active. Un visiteur sur son ordinateur ne peut
    pas enregistrer sur place : il lui faut son telephone, donc un QR — c'est
    le meme chemin d'entree que sur l'affiche.
    / The QR to record a clameur; None when no borne is open.
    """
    borne = Borne.objects.filter(active=True).order_by("nom").first()
    if not borne:
        return None

    cle = f"invitation:{borne.slug}"
    invitation = cache.get(cle)
    if invitation is not None:
        return invitation

    url = f"{settings.URL_PUBLIQUE.rstrip('/')}{reverse('capsules:accueil_borne', args=[borne.slug])}"
    invitation = {
        "borne": borne.nom,
        "url": url,
        # Correction moyenne : ce QR est lu sur un ecran, pas sur une affiche
        # exposee aux intemperies. / Medium correction: read from a screen.
        "qr_svg": segno.make(url, error="m").svg_inline(scale=8, border=0, dark="#0b0d14"),
    }
    cache.set(cle, invitation, DUREE_DU_CACHE_INVITATION)
    return invitation


def decrire_une_clameur(capsule) -> dict:
    """Tout ce dont la fiche et l'etoile ont besoin.
    / Everything the card and the star need."""
    return {
        "capsule": capsule,
        "tags": [lien.tag.nom for lien in capsule.tags_de_capsule.all()],
        "duree": _duree_lisible(capsule.duree_secondes),
        "audio": capsule.audio_a_servir.url if capsule.audio_a_servir else "",
        "x": round(capsule.position_x or 0.5, 4),
        "y": round(capsule.position_y or 0.5, 4),
        "teinte": _teinte_de_la_position(capsule.position_x or 0.5, capsule.position_y or 0.5),
        "segments": _colorer_les_voix(
            (capsule.transcription_raw or {}).get("segments") or []
        ),
    }


def _duree_lisible(secondes: int) -> str:
    minutes, reste = divmod(int(secondes or 0), 60)
    return f"{minutes} min {reste:02d}" if minutes else f"{reste} s"


# L'arc des teintes du ciel : du rose au dore, en passant par la terracotta.
# UNE ROUE COMPLETE SERAIT UNE FAUTE : sur un papier brun chaud, un point vert
# ou bleu ne se lit pas comme une voisine, il se lit comme une erreur. On garde
# la variete — trois familles bien distinctes — sans quitter la famille chaude.
# / A full colour wheel would put green and blue on warm brown paper: they would
#   read as mistakes, not as neighbours. The arc keeps variety inside the family.
TEINTE_DEPART = 350
ETENDUE_DES_TEINTES = 110


def _teinte_de_la_position(x: float, y: float) -> int:
    """La teinte suit l'angle depuis le centre du ciel, dans l'arc chaud.

    Les amas proches recoivent des teintes proches, et deux amas opposes
    s'opposent aussi en couleur — mais tous restent dans la meme famille.
    / Nearby clusters get nearby hues, all inside the warm family.
    """
    angle = (math.degrees(math.atan2(y - 0.5, x - 0.5)) + 180) % 360
    return int(TEINTE_DEPART + angle / 360 * ETENDUE_DES_TEINTES) % 360


@require_GET
def mentions_legales(request):
    return render(request, "capsules/mentions_legales.html")
