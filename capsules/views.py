"""Vues de la borne et de la lecture. / Borne and playback views."""

import logging

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
            "segments": (capsule.transcription_raw or {}).get("segments") or [],
            "tags": [lien.tag.nom for lien in capsule.tags_de_capsule.all()],
        },
    )


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
def mentions_legales(request):
    return render(request, "capsules/mentions_legales.html")
