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

    def print_ticket(self, capsule, url_capsule: str) -> str:
        """Imprime le ticket d'une capsule et rend le trade_no Sunmi.
        / Prints a capsule's ticket and returns the Sunmi trade_no."""
        raise NotImplementedError
