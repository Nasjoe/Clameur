"""Projet Clameur.

IMPORT A EFFET DE BORD — NE JAMAIS SUPPRIMER.
Sans cet import, Django ne connait pas l'application Celery et `.delay()`
part dans le vide, sans erreur. Le nom `celery_app` n'est reference nulle
part : un linter le croira mort.
/ Side-effect import. Without it, .delay() silently goes nowhere.
"""

from clameur.celery import app as celery_app

__all__ = ("celery_app",)
