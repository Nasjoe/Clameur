"""Reglages Django du projet Clameur. / Django settings for Clameur."""

import mimetypes
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# override=False : les variables injectees par docker-compose gagnent sur le .env
# / override=False: variables injected by docker-compose win over the .env file
load_dotenv(BASE_DIR / ".env", override=False)

CLE_DE_DEVELOPPEMENT = "cle-de-developpement-non-secrete"
SECRET_KEY = os.environ.get("SECRET_KEY", CLE_DE_DEVELOPPEMENT)

# DEFAUT `false`, ET C'EST DELIBERE. Un oubli dans le `.env` doit produire un
# site sur, pas un site bavard : en DEBUG, les traces d'exception partent aux
# visiteurs et les fichiers statiques perdent leur empreinte alors que nginx
# les sert avec un cache d'un an.
# / Default false: a forgotten variable must yield a safe site, not a chatty one.
DEBUG = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
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
    # DAPHNE EN PREMIER, ET AVANT `staticfiles`. C'est ce qui fait basculer
    # `runserver` en ASGI : sans lui, les routes /ws/ repondent 404 en
    # developpement et aucune mise a jour temps reel n'arrive.
    # / daphne first: this is what switches runserver to ASGI.
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "solo",
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
ASGI_APPLICATION = "clameur.asgi.application"

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

# Meme oubli de Python pour les polices. Ici la consequence est plus sournoise :
# le `<link rel="preload" as="font" type="font/woff2">` de base.html est
# IGNORE quand le type annonce ne correspond pas, et le fichier est alors
# telecharge une seconde fois au moment ou la feuille de styles le reclame.
# / Same gap for fonts: a mismatched type makes the preload be discarded and
#   the file fetched twice.
mimetypes.add_type("font/woff2", ".woff2")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# EN PRODUCTION, LES STATIQUES PORTENT LEUR EMPREINTE DANS LEUR NOM
# (constellation.a1b2c3d4.js). Sans cela, un visiteur qui a l'ancien fichier
# en cache continue de l'executer apres un deploiement : la page se casse en
# silence, chez lui seul, et on ne peut pas le reproduire. Le risque est reel
# ici — les tickets restent colles dans la rue pendant des semaines.
# En developpement on garde les noms simples, plus lisibles pour deboguer.
# / Hashed names in production: a stale cached file breaks the page silently.
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        },
    }
MEDIA_URL = "medias/"
MEDIA_ROOT = BASE_DIR / "medias"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# L'URL absolue encodee dans le QR du ticket. Un ticket colle dans la rue
# n'a pas de requete HTTP pour deviner son domaine.
# / The absolute URL printed in the ticket's QR code.
URL_PUBLIQUE = os.environ.get("URL_PUBLIQUE", "http://localhost:8000")

# Obligations d'hebergeur (LCEN). Sans ces deux valeurs, personne ne peut
# signaler une clameur : la page des mentions le dit alors franchement plutot
# que d'afficher une adresse qui n'existe pas.
# / Without these, nobody can report a clameur; the page says so plainly.
EDITEUR = os.environ.get("EDITEUR", "")
CONTACT = os.environ.get("CONTACT", "")

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
# La couche de canaux passe par Redis : gunicorn (qui publie apres une
# transcription) et daphne (qui tient les connexions) sont deux process
# distincts. Une couche en memoire ne les relierait pas.
# / Redis-backed layer: the publisher and the socket holder are separate processes.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

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

if not DEBUG and SECRET_KEY == CLE_DE_DEVELOPPEMENT:
    raise ImproperlyConfigured(
        "SECRET_KEY absente du .env alors que DEBUG est faux. Le site "
        "tournerait avec la clé de développement, publiée dans le dépôt : "
        "les sessions et les jetons CSRF de tout le monde seraient forgeables."
    )

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
