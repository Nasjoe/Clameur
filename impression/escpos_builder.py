"""Construction des octets ESC/POS d'un ticket.
/ Builds a ticket's ESC/POS bytes.

LA CONSTRUCTION EST SEPAREE DE L'ENVOI. Les deux backends — le reel et le mock —
appellent cette fonction : le mock est donc un vrai test de bout en bout du
ticket, pas un bouchon.
/ Building is separate from sending, so the mock truly tests the real ticket.
"""

from impression.sunmi_cloud_printer import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    DIFFUSE_DITHER,
    SunmiCloudPrinter,
)

# Largeur de la photo sur le ticket, en points. Deux tiers de la laize en
# 80 mm : assez grand pour etre regarde, assez petit pour ne pas devorer le
# rouleau. / Photo width in dots: two thirds of an 80 mm roll.
LARGEUR_PHOTO = 384


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

    ticket.appendQRcode(module_size=6, ec_level=1, text=url_capsule)
    ticket.lineFeed()

    ticket.appendText("Scanne. Ecoute.\n")
    ticket.setAlignment(ALIGN_LEFT)
    ticket.lineFeed(3)
    ticket.cutPaper(full_cut=False)

    return ticket.orderData


def _duree_lisible(secondes: int) -> str:
    """La duree annoncee honnetement : personne n'aime decouvrir qu'il s'est
    engage dans huit minutes. / Duration stated honestly."""
    minutes, reste = divmod(int(secondes or 0), 60)
    if minutes:
        return f"{minutes} min {reste:02d} s"
    return f"{reste} s"
