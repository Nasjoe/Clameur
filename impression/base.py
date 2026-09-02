"""Interface des backends d'impression (pattern Strategy).
/ Printing backend interface (Strategy pattern).

Pas d'ABC ni de metaclasse : une simple classe avec NotImplementedError, c'est
plus lisible et il n'y a rien a gagner de plus.
/ No ABC, no metaclass: a plain class is more readable here.
"""


class PrinterBackend:
    def can_print(self) -> tuple[bool, str]:
        """Verifie les preconditions AVANT d'essayer d'imprimer.

        Echouer au milieu d'un envoi laisse un job dans un etat trouble ;
        refuser d'emblee avec un message clair est toujours preferable.
        / Checks preconditions before attempting to print.

        :return: (impression possible, message d'erreur si elle ne l'est pas)
        """
        raise NotImplementedError

    def print_ticket(self, capsule, url_capsule: str, reference="") -> str:
        """Imprime le ticket d'une capsule et rend le trade_no Sunmi.

        `reference` IDENTIFIE LA DEMANDE, PAS LA CAPSULE, et c'est ce qui
        permet d'imprimer un second ticket de la meme clameur. Sunmi
        deduplique sur le trade_no : sans elle, une reimpression porterait le
        meme numero que la premiere et serait ignoree en silence. On y passe
        l'identifiant du `JobImpression` — un rejeu du meme job garde donc son
        numero et reste idempotent, une nouvelle demande en obtient un autre.
        / It identifies the REQUEST, not the capsule: Sunmi deduplicates on the
          trade_no, so a reprint needs its own. The JobImpression's id keeps a
          redelivered task idempotent while a new request gets a new number.
        """
        raise NotImplementedError
