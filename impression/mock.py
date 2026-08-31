"""Backend d'impression Mock.
/ Mock printing backend.

CE N'EST PAS UN BOUCHON. Il construit LES MEMES octets ESC/POS que le backend
reel, puis les decode en texte lisible dans la console. Si le ticket est
lisible ici, il le sera sur le papier — et on peut travailler sa mise en page
sans consommer de rouleau.
/ Not a stub: it builds the same bytes and decodes them, so it tests the real ticket.
"""

import logging

from impression.base import PrinterBackend
from impression.escpos_builder import construire_le_ticket

logger = logging.getLogger(__name__)

LARGEUR_CADRE = 48


def decoder_escpos(octets: bytes) -> list[str]:
    """Extrait le texte lisible d'un flux ESC/POS.

    On ne cherche pas a interpreter les commandes : on garde les suites
    d'octets imprimables et decodables en UTF-8. L'URL du QR code apparait
    ainsi naturellement, puisqu'elle voyage en clair dans sa commande.
    / Keeps printable UTF-8 runs; the QR payload shows up on its own.
    """
    lignes: list[str] = []
    tampon = bytearray()

    for octet in octets:
        if octet == 0x0A:  # saut de ligne
            lignes.append(_vider(tampon))
            tampon.clear()
        elif octet >= 0x20 and octet != 0x7F:
            tampon.append(octet)
        else:
            # Octet de controle : on coupe le mot en cours sans perdre
            # ce qui precede. / Control byte: flush without losing text.
            morceau = _vider(tampon)
            if morceau:
                lignes.append(morceau)
            tampon.clear()

    dernier = _vider(tampon)
    if dernier:
        lignes.append(dernier)

    # Les suites d'un seul caractere sont presque toujours des residus de
    # commandes, pas du texte. / Single characters are command residue.
    return [ligne for ligne in lignes if len(ligne.strip()) > 1]


def _vider(tampon: bytearray) -> str:
    return bytes(tampon).decode("utf-8", errors="ignore").strip()


class MockBackend(PrinterBackend):
    """Imprime dans les journaux. Toujours disponible."""

    def __init__(self, borne):
        self.borne = borne

    def can_print(self) -> tuple[bool, str]:
        return True, ""

    def print_ticket(self, capsule, url_capsule: str) -> str:
        octets = construire_le_ticket(capsule, self.borne.dots_par_ligne, url_capsule)
        cadre = ["+" + "-" * LARGEUR_CADRE + "+"]
        for ligne in decoder_escpos(octets):
            cadre.append("| " + ligne[: LARGEUR_CADRE - 2].ljust(LARGEUR_CADRE - 2) + " |")
        cadre.append("+" + "-" * LARGEUR_CADRE + "+")
        logger.info("Ticket (mock) :\n%s", "\n".join(cadre))
        return f"mock_{capsule.uuid}"
