"""Reglages Django du projet Clameur. / Django settings for Clameur."""

import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# override=False : les variables injectees par docker-compose gagnent sur le .env
# / override=False: variables injected by docker-compose win over the .env file
load_dotenv(BASE_DIR / ".env", override=False)

SECRET_KEY = os.environ.get("SECRET_KEY", "cle-de-developpement-non-secrete")
DEBUG = os.environ.get("DEBUG", "true").lower() in ("true", "1", "yes")
ALLOWED_HOSTS = [
    hote.strip()
    for hote in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,web").split(",")
    if hote.strip()
]

# DERRIERE TRAEFIK ET NGINX, DJANGO NE SAIT PAS QU'IL EST EN HTTPS.
# Sans cet en-tete, `request.is_secure()` est faux : les URL absolues sortent
# en http://, la protection CSRF rejette les POST du formulaire, et surtout le
# navigateur juge la page non securisee — donc REFUSE l'acces au micro. La
# borne ne fonctionne alors pas du tout.
# / Behind Traefik+nginx Django would think it is on HTTP: no CSRF, no microphone.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Django exige l'origine complete, schema compris, pour valider un POST.
# / Django needs the full origin, scheme included, to accept a POST.
CSRF_TRUSTED_ORIGINS = [
    origine.strip()
    for origine in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origine.strip()
]
if os.environ.get("DOMAIN"):
    ALLOWED_HOSTS.append(os.environ["DOMAIN"])
    CSRF_TRUSTED_ORIGINS.append(f"https://{os.environ['DOMAIN']}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "bornes",
    "capsules",
    "impression",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "clameur.urls"
WSGI_APPLICATION = "clameur.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "clameur"),
        "USER": os.environ.get("POSTGRES_USER", "clameur"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "clameur_dev"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

# Python ne connait pas l'extension .m4a : sans cette ligne, Django sert
# l'audio en `application/octet-stream` et le navigateur affiche un lecteur
# muet a « 0:00 / 0:00 ». Le fichier est pourtant valide — c'est le type MIME
# qui manque. A repercuter dans la configuration nginx en production.
# / Python does not know .m4a: without this the browser gets octet-stream
#   and shows a dead player.
mimetypes.add_type("audio/mp4", ".m4a")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "medias/"
MEDIA_ROOT = BASE_DIR / "medias"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# L'URL absolue encodee dans le QR du ticket. Un ticket colle dans la rue
# n'a pas de requete HTTP pour deviner son domaine.
# / The absolute URL printed in the ticket's QR code.
URL_PUBLIQUE = os.environ.get("URL_PUBLIQUE", "http://localhost:8000")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Celery. La publication n'en depend jamais (invariant I2) : un enqueue qui
# echoue est rattrape depuis la console.
# / Publication never depends on Celery (invariant I2).
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ACKS_LATE = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Le cache porte deux garde-fous : l'etat de l'imprimante (30 s) et le throttle
# anti-abus. Sans lui, chaque visiteur taperait l'API Sunmi.
# / The cache carries printer state and the anti-abuse throttle.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Mistral : Voxtral pour la transcription, mistral-embed pour les vecteurs.
# La cle vit dans l'environnement, JAMAIS en base.
# / Mistral key lives in the environment, NEVER in the database.
MISTRAL_MODELE_TRANSCRIPTION = "voxtral-mini-latest"
MISTRAL_MODELE_TAGS = "mistral-small-latest"
MISTRAL_MODELE_EMBEDDING = "mistral-embed"
MISTRAL_DIMENSIONS_EMBEDDING = 1024

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
