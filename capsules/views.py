"""Vues de l'enregistrement et de la lecture. / Recording and playback views."""

import logging
import math

import segno
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from bornes.models import Reglages
from capsules.garde_fous import adresse_ip, limite_atteinte
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

# Au-dela, la page devient trop lourde a charger d'un coup. La recherche est
# la pour retrouver ce qui n'est plus a l'ecran.
# / Beyond this the page is too heavy; search is what finds the rest.
PLAFOND_DE_LA_LISTE = 600

# Une journee. Au-dela, la valeur est forgee : on la ramene sans refuser
# l'enregistrement, qui lui est bien reel.
# / Beyond a day the value is forged; clamp it rather than reject the audio.
PLAFOND_DUREE_ANNONCEE = 86400

# Vingt-quatre heures : reecouter le lendemain compte pour une nouvelle
# ecoute, recharger la page dix fois dans l'heure non.
# / A day: listening again tomorrow counts, reloading ten times does not.
DUREE_MEMOIRE_DES_ECOUTES = 86400

# Le QR d'invitation ne change que si la reglages change : inutile de le
# regenerer pour chaque visiteur.
# / The invitation QR only changes with the reglages.
DUREE_DU_CACHE_INVITATION = 600

# L'echelle ne fixe que la finesse du trace : le viewBox fait le reste, et
# le CSS decide de la taille affichee.
# / Scale only sets the drawing's precision; the viewBox handles sizing.
ECHELLE_DU_QR = 8

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


def interroger_l_imprimante(reglages) -> dict:
    """Etat de l'imprimante, mis en cache 30 secondes.

    Sans ce cache, chaque visiteur qui ouvre la page declencherait un appel a
    l'API Sunmi. / Without this cache every visitor would hit the Sunmi API.
    """
    cle = "etat-imprimante"
    # Un cache indisponible ne doit pas faire tomber la page d'accueil du
    # lieu : on interroge, et on continue sans lui s'il ne repond pas.
    # / An unavailable cache must not take the reglages's welcome page down.
    try:
        etat = cache.get(cle)
        if etat is not None:
            return etat
    except Exception:
        logger.warning("cache indisponible pour l'etat de l'imprimante")

    from impression.tasks import choisir_le_backend

    backend = choisir_le_backend(reglages)
    if hasattr(backend, "est_en_ligne"):
        en_ligne, message = backend.est_en_ligne()
    else:
        en_ligne, message = backend.can_print()

    etat = {"en_ligne": en_ligne, "message": message}
    try:
        cache.set(cle, etat, DUREE_DU_CACHE_IMPRIMANTE)
    except Exception:
        logger.warning("cache indisponible : etat de l'imprimante non memorise")
    return etat


@require_GET
def accueil_enregistrement(request):
    """`/nouvelle` — la page ou l'on depose une clameur.

    Une adresse qui tient dans une phrase : c'est elle qu'on dit a voix haute
    et qu'on encode dans le QR de l'affiche. Il n'y a qu'un lieu, donc rien a
    designer. / One venue, so nothing to name: an address that fits a sentence.
    """
    reglages = Reglages.get_solo()
    return render(
        request,
        "capsules/borne.html",
        {
            "reglages": reglages,
            "imprimante": interroger_l_imprimante(reglages),
            "nombre_max_de_tags": NOMBRE_MAX_DE_TAGS,
        },
    )


@require_POST
def creer_capsule(request):
    """Recoit l'audio des l'arret de l'enregistrement.

    L'envoi a lieu AVANT la saisie du pseudo : cela met a profit le temps de
    frappe et garantit qu'un audio n'est jamais perdu si l'onglet se ferme.
    / Uploaded before the form is filled: the audio is never lost.
    """
    reglages = Reglages.get_solo()
    if not reglages.active:
        return JsonResponse({"erreur": _("Les enregistrements sont fermés.")}, status=403)

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
        reglages=reglages,
        audio_original=fichier,
        duree_secondes=_duree_annoncee(request.POST.get("duree")),
    )
    return JsonResponse({"uuid": str(capsule.uuid)})


def _duree_annoncee(valeur) -> int:
    """La duree telle que le client la declare, ramenee a quelque chose de sain.

    Elle arrive d'un POST public : `NaN`, `inf`, `1e300` ou un nombre negatif
    (un telephone qui resynchronise son horloge pendant l'enregistrement)
    faisaient tous un 500 — et le visiteur perdait sa voix sur une erreur
    qu'il ne pouvait ni comprendre ni contourner.
    / It comes from a public POST: NaN, inf and negative values all 500'd, and
      the visitor lost their recording to an error they could not act on.
    """
    try:
        secondes = int(float(valeur or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(secondes, PLAFOND_DUREE_ANNONCEE))


@require_POST
def publier_capsule(request, uuid):
    if limite_atteinte(request, "publication"):
        return JsonResponse({"erreur": _("Trop de publications.")}, status=429)

    # UN VERROU SUR LA LIGNE, PAS UNE SIMPLE LECTURE. Deux POST concurrents —
    # deux onglets, ou un reseau qui coupe pendant la reponse et un visiteur
    # qui reappuie — passaient tous deux le controle de statut avant le
    # premier enregistrement : deux normalisations, deux jobs, DEUX TICKETS.
    # Le verrou ne bloque que les requetes portant sur cette capsule-la.
    # / A row lock, not a read: two concurrent POSTs printed two tickets.
    with transaction.atomic():
        capsule = get_object_or_404(
            Capsule.objects.select_for_update(), uuid=uuid
        )

        if capsule.statut != StatutCapsule.BROUILLON:
            # Deja publiee : du point de vue du visiteur l'operation a reussi,
            # et son ticket est en train de sortir. Lui repondre une erreur le
            # ferait partir en croyant avoir echoue.
            # / Already published: from the visitor's side it worked.
            return JsonResponse({"uuid": str(capsule.uuid), "url": f"/c/{capsule.uuid}"})

        capsule.pseudo = (request.POST.get("pseudo") or "").strip()[:80]

        photo = request.FILES.get("photo")
        if photo:
            try:
                capsule.photo.save(
                    f"{capsule.uuid}.jpg", purger_les_exif(photo), save=False
                )
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
        Capsule.objects.select_related("reglages").prefetch_related("tags_de_capsule__tag"),
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
            "tags": _mots_cles(capsule),
            "duree": _duree_lisible(capsule.duree_secondes),
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
    # UNE ECOUTE PAR ADRESSE ET PAR CAPSULE, SANS COOKIE.
    # La deduplication cote navigateur ne protege de rien : une boucle de
    # `curl` portait une clameur a dix mille ecoutes, alors que ce compteur est
    # la seule mesure qui dira si les passants scannent vraiment, et qu'il
    # dimensionne les etoiles du ciel.
    #
    # On dedupliquait d'abord sur la session — mais elle etait CREEE par la
    # requete elle-meme : un client qui ne renvoyait pas le cookie obtenait une
    # cle neuve a chaque appel, et un simple passant repartait avec un cookie de
    # deux semaines, ce que les mentions legales promettent de ne pas faire.
    #
    # L'adresse est imparfaite — derriere le partage de connexion d'un lieu,
    # plusieurs personnes la partagent et une seule ecoute sera comptee. La
    # mesure est donc un plancher, jamais un compte exact. C'est le prix d'un
    # compteur sans cookie, et il est assume.
    # / Deduped by address, not by a session we would have to create. Behind a
    #   shared connection this undercounts: the figure is a floor, not a total.
    cle = f"ecoute:{adresse_ip(request)}:{uuid}"
    try:
        premiere_fois = cache.add(cle, 1, DUREE_MEMOIRE_DES_ECOUTES)
    except Exception:
        # Cache indisponible : on compte plutot que de perdre la mesure.
        # / Cache down: count rather than lose the measurement.
        premiere_fois = True

    if premiere_fois:
        Capsule.objects.filter(uuid=uuid, statut=StatutCapsule.PUBLIEE).update(
            nombre_ecoutes=F("nombre_ecoutes") + 1
        )
    return HttpResponse(status=204)


@staff_member_required
@require_GET
def affiche(request):
    """L'affiche A4 a coller au mur, avec le QR d'entree de la reglages.

    C'est le seul objet du projet que personne d'autre ne peut fabriquer, et
    sans elle rien n'existe : le QR est le seul chemin entre le mur et
    le telephone du visiteur.
    / The poster is the only path from the wall to the visitor's phone.
    """
    reglages = Reglages.get_solo()
    url_entree = f"{settings.URL_PUBLIQUE.rstrip('/')}{reverse('capsules:nouvelle')}"

    # Correction d'erreur haute : une affiche vit dehors, elle se salit, se
    # dechire, prend la pluie. Le niveau H tolere 30 % du code abime.
    # / High error correction: a poster gets dirty, torn and rained on.
    qr = segno.make(url_entree, error="h")

    return render(
        request,
        "capsules/affiche.html",
        {
            "reglages": reglages,
            "url_entree": url_entree,
            "qr_svg": qr.svg_inline(scale=12, border=0, dark="#0b0d14"),
        },
    )


@require_GET
def liste(request):
    """`/` — toutes les clameurs, la plus récente d'abord, et une recherche.

    LA LISTE NE DEPEND D'AUCUN VECTEUR, et c'est tout l'intérêt du changement.
    Le ciel n'affichait que les clameurs déjà projetées : une clameur publiée
    pendant un événement restait invisible jusqu'au prochain recalcul, lancé à
    la main. Ici elle est là dès sa publication.
    / The list needs no vector: a clameur appears the moment it is published,
      where the sky waited for a manual projection.
    """
    recherche = (request.GET.get("q") or "").strip()

    capsules = Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
    if recherche:
        # UN `icontains`, PAS UN INDEX PLEIN TEXTE. Quelques centaines de
        # clameurs tiennent dans un balayage sans qu'on le sente, et une
        # recherche plein texte demanderait un index, une migration et un
        # vocabulaire de langue — pour un corpus qui tient dans une salle.
        # / A scan is instant at this size; full-text would cost an index, a
        #   migration and a language configuration for a room-sized corpus.
        capsules = capsules.filter(
            Q(titre__icontains=recherche)
            | Q(pseudo__icontains=recherche)
            | Q(transcription_texte__icontains=recherche)
            | Q(tags_de_capsule__tag__nom__icontains=recherche)
        # `distinct` : sans lui, une clameur dont DEUX mots-cles correspondent
        # revient deux fois — la jointure la duplique.
        # / Without distinct, two matching tags return the row twice.
        ).distinct()

    capsules = (
        capsules.prefetch_related("tags_de_capsule__tag")
        .order_by("-publiee_le")[:PLAFOND_DE_LA_LISTE]
    )
    clameurs = [decrire_une_clameur(capsule) for capsule in capsules]

    # HTMX ne remplace que la liste : lui renvoyer la page entiere imbriquerait
    # un second en-tete et un second champ de recherche dans le premier.
    # / HTMX swaps the list alone; a whole page would nest a second header.
    pour_htmx = bool(request.headers.get("HX-Request"))
    gabarit = "capsules/_resultats.html" if pour_htmx else "capsules/liste.html"
    return render(
        request,
        gabarit,
        {
            "clameurs": clameurs,
            "nombre": len(clameurs),
            # LE CORPUS ENTIER, ET NON CE QUE LA RECHERCHE A RETENU. C'est lui
            # que la description de partage annonce : « /?q=zzzz » partage tel
            # quel disait « aucune clameur encore » a son destinataire, alors
            # que le site en porte cent.
            # / The whole corpus, not the search result: an empty search used
            #   to tell the recipient the project had not started.
            "nombre_en_tout": Capsule.objects.filter(
                statut=StatutCapsule.PUBLIEE
            ).count(),
            "recherche": recherche,
            "invitation": invitation_a_enregistrer(request),
            "pour_htmx": pour_htmx,
        },
    )


# EN SOMMEIL DEPUIS LE 2026-09-01, avec la constellation. La vue n'est plus
# routee : `/` rend la liste. On la garde entiere, elle et son gabarit, son
# JavaScript et la commande `projeter_la_constellation`, pour le jour ou le
# ciel reviendra. Rien ne l'appelle.
# / Dormant since the constellation was shelved: no longer routed, kept whole.
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
    """Le QR a scanner pour deposer une clameur, ou None si le lieu est ferme.

    Un visiteur sur son ordinateur ne peut pas enregistrer sur place : il lui
    faut son telephone, donc un QR — c'est le meme chemin d'entree que sur
    l'affiche. Le bouton l'accompagne pour qui lit deja depuis un telephone.
    / The QR for whoever arrives with a phone; the button for whoever reads on one.
    """
    reglages = Reglages.get_solo()
    if not reglages.active:
        # Proposer d'enregistrer quand le lieu est ferme serait une promesse en
        # l'air. / Offering to record while closed would be an empty promise.
        return None

    cle = "invitation"
    try:
        invitation = cache.get(cle)
        if invitation is not None:
            return invitation
    except Exception:
        logger.warning("cache indisponible pour l'invitation")

    url = f"{settings.URL_PUBLIQUE.rstrip('/')}{reverse('capsules:nouvelle')}"
    invitation = {
        "lieu": reglages.nom,
        "url": url,
        "chemin": reverse("capsules:nouvelle"),
        # Correction moyenne : ce QR est lu sur un ecran, pas sur une affiche
        # exposee aux intemperies. / Medium correction: read from a screen.
        "qr_svg": _qr_avec_viewbox(url),
    }
    try:
        cache.set(cle, invitation, DUREE_DU_CACHE_INVITATION)
    except Exception:
        logger.warning("cache indisponible : invitation non memorisee")
    return invitation


def decrire_une_clameur(capsule) -> dict:
    """Tout ce dont la fiche et l'etoile ont besoin.
    / Everything the card and the star need."""
    return {
        "capsule": capsule,
        "tags": _mots_cles(capsule),
        "duree": _duree_lisible(capsule.duree_secondes),
        "audio": capsule.audio_a_servir.url if capsule.audio_a_servir else "",
        "type_mime": capsule.type_mime_a_servir,
        "x": round(capsule.position_x or 0.5, 4),
        "y": round(capsule.position_y or 0.5, 4),
        "teinte": _teinte_de_la_capsule(capsule),
        "segments": _colorer_les_voix(
            (capsule.transcription_raw or {}).get("segments") or []
        ),
    }


def _mots_cles(capsule) -> list[str]:
    """Les mots-cles a lire, sans doublon et dans l'ordre d'ajout.

    L'auteur ecrit « quartier », le modele trouve « quartier » : la fiche
    affichait « · quartier · quartier ». Les deux origines restent distinctes
    en base — elles ne se melangent jamais, c'est le §10 de la spec — mais la
    ligne qu'on lit, elle, ne repete pas. `dict.fromkeys` dedoublonne sans
    perdre l'ordre. / Deduplicated for reading only; the two origins stay
    separate in the database.
    """
    return list(dict.fromkeys(
        lien.tag.nom for lien in capsule.tags_de_capsule.all()
    ))


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


def _qr_avec_viewbox(url: str) -> str:
    """Le QR, muni d'un `viewBox` pour qu'il se mette a l'echelle.

    Segno rend un `<svg>` avec des `width`/`height` fixes et AUCUN `viewBox`.
    Un `width: 100%` en CSS etire alors le canevas sans redimensionner le
    dessin : le code se retrouve tasse dans un coin, decentre. Le viewBox lui
    rend son ratio, et le centrage devient l'affaire du CSS.
    / Segno emits no viewBox: CSS width stretches the canvas but not the
      drawing, leaving the code stuck in a corner.
    """
    qr = segno.make(url, error="m")
    cote = qr.symbol_size(scale=ECHELLE_DU_QR, border=0)[0]
    svg = qr.svg_inline(scale=ECHELLE_DU_QR, border=0, dark="#0b0d14")
    return svg.replace(
        "<svg ", f'<svg viewBox="0 0 {cote} {cote}" ', 1
    )


def _teinte_de_la_capsule(capsule) -> int:
    """La teinte d'une fiche, tiree de son UUID.

    Elle derivait de la position dans le ciel : sans ciel, toutes les fiches
    prenaient la meme couleur. L'UUID ne change jamais, donc une clameur garde
    sa teinte d'une visite a l'autre, et le corpus reste bariole dans l'arc
    chaud du projet.
    / It came from the position in the sky; the UUID keeps each card's hue
      stable across visits and the corpus varied.
    """
    if capsule.position_x is not None and capsule.position_y is not None:
        return _teinte_de_la_position(capsule.position_x, capsule.position_y)
    return int(TEINTE_DEPART + capsule.uuid.int % ETENDUE_DES_TEINTES) % 360


def _teinte_de_la_position(x: float, y: float) -> int:
    """La teinte suit l'angle depuis le centre du ciel, dans l'arc chaud.

    Les amas proches recoivent des teintes proches, et deux amas opposes
    s'opposent aussi en couleur — mais tous restent dans la meme famille.
    / Nearby clusters get nearby hues, all inside the warm family.
    """
    angle = (math.degrees(math.atan2(y - 0.5, x - 0.5)) + 180) % 360
    return int(TEINTE_DEPART + angle / 360 * ETENDUE_DES_TEINTES) % 360


# LES DEPIAUTEURS DE LIENS NE SONT PAS DES MOTEURS. Ils chargent une page une
# fois, pour en tirer un titre et une image, et ils n'indexent rien. Plusieurs
# d'entre eux respectent robots.txt : un `Disallow` global les ferait renoncer,
# et un lien de clameur arriverait nu dans une conversation — precisement ce
# que les metadonnees de partage existent pour eviter.
# / Several unfurlers obey robots.txt: a blanket Disallow would strip every
#   shared link of its preview, which is the opposite of what we want.
DEPIAUTEURS_DE_LIENS = [
    "Twitterbot",
    "facebookexternalhit",  # Facebook, Messenger et WhatsApp
    "WhatsApp",
    "LinkedInBot",
    "Slackbot-LinkExpanding",
    "Discordbot",
    "TelegramBot",
    "Mastodon",
]


@require_GET
def robots(request):
    """Ce que le site demande aux robots : passer leur chemin.

    Une clameur est deposee pour un mur, pas pour un moteur de recherche. Les
    UUID ne sont pas enumerables, mais la constellation les liste toutes : un
    moteur qui l'explore trouverait le corpus entier.
    / A clameur is left for a wall, not for a search engine.
    """
    return render(
        request, "robots.txt",
        {"depiauteurs": DEPIAUTEURS_DE_LIENS},
        content_type="text/plain; charset=utf-8",
    )


@require_GET
def icone_du_site(request):
    """`/favicon.ico`, que les robots et les vieux navigateurs demandent seuls.

    La page declare ses icones, mais beaucoup d'agents tapent cette adresse
    sans lire le HTML. On resout le chemin ICI et non a l'import : en
    production les statiques portent leur empreinte, et le manifeste qui la
    donne n'existe qu'apres `collectstatic`.
    / Resolved per request: in production the hashed name comes from a
      manifest that only exists after collectstatic.
    """
    return redirect(staticfiles_storage.url("capsules/marque/icone-32.png"))


@require_GET
def mentions_legales(request):
    return render(
        request,
        "capsules/mentions_legales.html",
        {"editeur": settings.EDITEUR, "contact": settings.CONTACT},
    )
