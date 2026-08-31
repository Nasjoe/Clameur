"""Backend d'impression Sunmi Cloud, en mode push direct.
/ Sunmi Cloud printing backend, direct push mode.

Un seul appel sortant vers openapi.sunmi.com : aucun endpoint n'est expose, le
serveur peut vivre derriere un NAT.
/ Outbound only: no exposed endpoint, the server may live behind a NAT.
"""

import logging
import os
import time

from impression.base import PrinterBackend
from impression.escpos_builder import construire_le_ticket
from impression.sunmi_cloud_printer import SunmiCloudPrinter

logger = logging.getLogger(__name__)


class SunmiCloudBackend(PrinterBackend):
    def __init__(self, borne):
        self.borne = borne

    def _pilote(self) -> SunmiCloudPrinter:
        return SunmiCloudPrinter(
            dots_per_line=self.borne.dots_par_ligne,
            app_id=os.environ.get("SUNMI_APP_ID", ""),
            app_key=os.environ.get("SUNMI_APP_KEY", ""),
            printer_sn=self.borne.numero_serie_imprimante,
        )

    def can_print(self) -> tuple[bool, str]:
        if not self.borne.numero_serie_imprimante:
            return False, "Numéro de série Sunmi manquant sur la borne."
        if not os.environ.get("SUNMI_APP_ID"):
            return False, "SUNMI_APP_ID non configuré."
        if not os.environ.get("SUNMI_APP_KEY"):
            return False, "SUNMI_APP_KEY non configuré."
        return True, ""

    def est_en_ligne(self) -> tuple[bool, str]:
        """Interroge Sunmi sur l'etat de l'imprimante.

        Ne leve jamais : une panne de l'API ne doit pas empecher d'afficher la
        page d'accueil de la borne.
        / Never raises: an API outage must not break the welcome page.
        """
        possible, message = self.can_print()
        if not possible:
            return False, message
        try:
            reponse = self._pilote().onlineStatus(self.borne.numero_serie_imprimante)
        except Exception as erreur:
            logger.warning("onlineStatus injoignable : %s", erreur)
            return False, "Imprimante injoignable."
        donnees = reponse.get("data") or {}
        en_ligne = donnees.get("status") in ("online", 1, "1", True)
        return en_ligne, "" if en_ligne else "Imprimante hors ligne."

    def print_ticket(self, capsule, url_capsule: str) -> str:
        pilote = self._pilote()
        pilote.appendRawData(
            construire_le_ticket(capsule, self.borne.dots_par_ligne, url_capsule)
        )
        numero = f"{self.borne.numero_serie_imprimante}_{int(time.time())}"
        pilote.pushContent(
            trade_no=numero,
            sn=self.borne.numero_serie_imprimante,
            count=1,
            media_text="Clameur",
        )
        return numero
