"""Construction des octets ESC/POS d'un ticket.
/ Builds a ticket's ESC/POS bytes.

LA CONSTRUCTION EST SEPAREE DE L'ENVOI. Les deux backends — le reel et le mock —
appellent cette fonction : le mock est donc un vrai test de bout en bout du
ticket, pas un bouchon.
/ Building is separate from sending, so the mock truly tests the real ticket.
"""

import logging
import random
from pathlib import Path

import numpy as np

from impression.qart import dessiner_le_qr
from impression.sunmi_cloud_printer import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    DIFFUSE_DITHER,
    SunmiCloudPrinter,
)

logger = logging.getLogger(__name__)

# Largeur de la photo sur le ticket, en points. Deux tiers de la laize en
# 80 mm : assez grand pour etre regarde, assez petit pour ne pas devorer le
# rouleau. / Photo width in dots: two thirds of an 80 mm roll.
LARGEUR_PHOTO = 384

# Les pictos que le QR dessine, un tire au hasard par ticket. Credits dans
# LICENCES.txt du meme dossier. / One pictogram drawn at random per ticket.
DOSSIER_DES_PICTOS = Path(__file__).resolve().parent / "pictos"

# 4 modules blancs autour du code : la norme QR l'exige pour le lire.
# 7 points par module = 0,9 mm en 203 dpi, soit un QR de 57 mm en 80 mm.
# / Quiet zone required by the QR standard; 7 dots = 0.9 mm per module.
ZONE_DE_SILENCE = 4
POINTS_PAR_MODULE_MAX = 7


def construire_le_ticket(capsule, dots_par_ligne: int, url_capsule: str) -> bytes:
    """Rend les octets ESC/POS du ticket d'une capsule.

    :param capsule: la Capsule a imprimer
    :param dots_par_ligne: 576 pour du 80 mm, 384 pour du 58 mm
    :param url_capsule: l'URL absolue encodee dans le QR code
    """
    # Le pilote sert ici de simple constructeur : httpPost n'est jamais appele,
    # les identifiants factices sont donc sans consequence.
    # / Used as a pure builder here; httpPost is never called.
    ticket = SunmiCloudPrinter(
        dots_per_line=dots_par_ligne,
        app_id="constructeur",
        app_key="constructeur",
        printer_sn="constructeur",
    )

    ticket.restoreDefaultSettings()

    # POLICE VECTORIELLE SUNMI, PAS LA MATRICIELLE PAR DEFAUT. Sur le papier de
    # la NT311, la matricielle crenelait les minuscules et rendait le « · »
    # des tags en « -- ». Compare le 2026-09-11, avec l'imprimante reglee en
    # Quality 100 et « fine print mode » (reglages de la machine, pas du code).
    # / Sunmi vector font: the default bitmap font made lowercase jagged.
    ticket.selectAsciiCharFont(1)
    ticket.selectOtherCharFont(1)
    ticket.setHarfBuzzAsciiCharSize(16)
    ticket.setHarfBuzzOtherCharSize(16)

    ticket.setAlignment(ALIGN_CENTER)

    if capsule.photo:
        # DIFFUSE_DITHER EXPLICITEMENT. Le defaut du pilote est le seuillage,
        # qui transforme une photo en aplats noirs illisibles.
        # / Explicit diffusion dithering: the driver's default would be unusable.
        ticket.appendImage(capsule.photo.path, mode=DIFFUSE_DITHER, width=LARGEUR_PHOTO)
        ticket.lineFeed()

    ticket.setPrintModes(bold=True, double_h=True, double_w=False)
    ticket.appendText("UNE CLAMEUR\n")
    ticket.setPrintModes(bold=False, double_h=False, double_w=False)
    ticket.lineFeed()

    ticket.appendText(f"{capsule.pseudo or 'anonyme'}\n")

    noms_de_tags = [lien.tag.nom for lien in capsule.tags_de_capsule.all()[:3]]
    if noms_de_tags:
        ticket.appendText(f"{' · '.join(noms_de_tags)}\n")

    ticket.appendText(f"{_duree_lisible(capsule.duree_secondes)}\n")
    ticket.lineFeed(2)

    _poser_le_qr(ticket, url_capsule, dots_par_ligne)
    ticket.lineFeed()

    ticket.appendText("Scanne. Ecoute.\n")
    ticket.setAlignment(ALIGN_LEFT)
    ticket.lineFeed(3)
    ticket.cutPaper(full_cut=False)

    return ticket.orderData


def _poser_le_qr(ticket, url_capsule: str, dots_par_ligne: int) -> None:
    """Le QR qui dessine un picto ; a defaut, le QR natif de l'imprimante.

    Un ticket sans QR lisible est le pire echec du parcours : toute panne ici
    retombe sur le QR natif, jamais sur une exception.
    / Any failure falls back to the printer's own QR code.
    """
    try:
        picto = random.choice(sorted(DOSSIER_DES_PICTOS.glob("*.png")))
        grille = dessiner_le_qr(url_capsule, picto)
        ticket.appendRawData(_en_image_raster(grille, dots_par_ligne))
    except Exception:
        logger.warning("QR image impossible, repli sur le QR natif", exc_info=True)
        ticket.appendQRcode(module_size=6, ec_level=1, text=url_capsule)


def _en_image_raster(grille, dots_par_ligne: int) -> bytes:
    """La grille du QR en commande `GS v 0` : un bit par point, 1 = noir.

    Ecrite ici plutot que par `appendImage`, qui avale en silence toute image
    qu'il n'arrive pas a ouvrir : le ticket sortirait sans QR, et sans erreur.
    / Written directly: appendImage silently drops images it cannot open.
    """
    avec_silence = np.pad(grille, ZONE_DE_SILENCE, constant_values=False)
    points_par_module = min(POINTS_PAR_MODULE_MAX, dots_par_ligne // avec_silence.shape[0])
    if points_par_module < 1:
        raise ValueError(f"{dots_par_ligne} points par ligne : trop etroit pour le QR")
    points = avec_silence.repeat(points_par_module, axis=0).repeat(points_par_module, axis=1)
    lignes = np.packbits(points, axis=1)
    hauteur, octets_par_ligne = lignes.shape
    return (
        b"\x1d\x76\x30\x00"
        + octets_par_ligne.to_bytes(2, "little")
        + hauteur.to_bytes(2, "little")
        + lignes.tobytes()
    )


def _duree_lisible(secondes: int) -> str:
    """La duree annoncee honnetement : personne n'aime decouvrir qu'il s'est
    engage dans huit minutes. / Duration stated honestly."""
    minutes, reste = divmod(int(secondes or 0), 60)
    if minutes:
        return f"{minutes} min {reste:02d} s"
    return f"{reste} s"
