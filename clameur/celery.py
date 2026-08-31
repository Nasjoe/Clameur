"""Application Celery du projet. / Project Celery application."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clameur.settings")

app = Celery("clameur")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
