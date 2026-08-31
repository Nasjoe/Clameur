# Clameur — Borne : plan d'implémentation

> **Pour les agents :** utiliser `superpowers:executing-plans`. Les étapes sont des cases à cocher.

**But :** une borne qui permet d'enregistrer une capsule audio depuis son téléphone et de repartir avec un ticket thermique portant un QR code vers cette capsule.

**Architecture :** trois apps Django (`bornes`, `capsules`, `impression`). La publication est synchrone et ne dépend de rien ; l'enrichissement sémantique est asynchrone et facultatif. L'impression suit un pattern Strategy avec un backend Mock qui décode l'ESC/POS en texte lisible.

**Stack :** Python 3.14, uv, Django 6, HTMX, JS vanilla, PostgreSQL + pgvector, Redis, Celery, ffmpeg, Mistral (Voxtral + mistral-embed), imprimante Sunmi Cloud NT311.

**Spec :** `docs/superpowers/specs/2026-08-31-clameur-borne-design.md` — à lire avant toute tâche.

## Contraintes globales

- **AUCUNE opération `git` sans accord explicite du mainteneur.** Ni `commit`, ni `add`, ni `checkout --`, ni `stash`, ni `restore`, ni `reset`. Les étapes « point de contrôle » de ce plan **ne committent pas** : elles marquent un état vérifiable. Le mainteneur committe lui-même.
- **Jamais de mention `Co-Authored-By` nulle part.**
- `ruff format` et `ruff check --fix` : uniquement sur des fichiers **neufs**.
- Secrets en variables d'environnement uniquement : `MISTRAL_API_KEY`, `SUNMI_APP_ID`, `SUNMI_APP_KEY`. Jamais en base, jamais versionnés.
- Le numéro de série de l'imprimante **n'est pas un secret** : il vit sur le modèle `Borne`.
- Vecteurs `mistral-embed` : **1024 dimensions**, exactement.
- Ticket : **576 dots** (80 mm), configurable par borne.
- Style : skill `djc` — noms explicites en français, i18n dès l'écriture, pas d'abstraction prématurée.
- Les trois invariants I1/I2/I3 de la spec §4 sont testés en tâche 7. Ils priment sur toute autre considération.

---

### Tâche 1 : socle — uv, Docker, Django

**Fichiers :**
- Créer : `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `manage.py`
- Créer : `clameur/__init__.py`, `clameur/settings.py`, `clameur/urls.py`, `clameur/celery.py`, `clameur/wsgi.py`
- Créer : `tests/test_socle.py`

**Produit :** un projet Django démarrable, une base PostgreSQL avec l'extension `vector`, un worker Celery joignable.

- [ ] **Étape 1 : `pyproject.toml`**

```toml
[project]
name = "clameur"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "django>=6",
    "django-htmx>=1.27",
    "psycopg[binary]>=3.2",
    "pgvector>=0.3",
    "celery[redis]>=5.4",
    "redis>=5.0",
    "mistralai>=1.0",
    "pillow>=11",
    "requests>=2.32",
    "numpy>=2",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-django>=4.9", "ruff>=0.8"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "clameur.settings"
python_files = ["test_*.py"]

[tool.ruff.lint.per-file-ignores]
# Les imports a effet de bord ne doivent jamais etre supprimes par --fix.
"**/admin.py" = ["F401"]
"**/apps.py" = ["F401"]
"**/__init__.py" = ["F401"]
```

- [ ] **Étape 2 : `.env.example`**

```bash
DEBUG=true
SECRET_KEY=change-moi
POSTGRES_DB=clameur
POSTGRES_USER=clameur
POSTGRES_PASSWORD=clameur_dev
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/0
MISTRAL_API_KEY=
SUNMI_APP_ID=
SUNMI_APP_KEY=
```

- [ ] **Étape 3 : `docker-compose.yml`**

Quatre services. `db` utilise l'image `pgvector/pgvector:pg17` — elle embarque l'extension, inutile de la compiler.

```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: ["donnees_db:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10

  web:
    build: .
    command: uv run python manage.py runserver 0.0.0.0:8000
    volumes: [".:/app"]
    ports: ["8000:8000"]
    env_file: [.env]
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}

  celery:
    build: .
    command: uv run celery -A clameur worker -l info
    volumes: [".:/app"]
    env_file: [.env]
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}

volumes:
  donnees_db:
```

- [ ] **Étape 4 : `Dockerfile`**

ffmpeg est une dépendance de l'image, pas du poste du mainteneur.

```dockerfile
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-install-project
COPY . .
```

- [ ] **Étape 5 : `clameur/settings.py`**

Points obligatoires : lecture des variables via `os.environ.get`, `INSTALLED_APPS` avec `django_htmx` puis les trois apps, `MIDDLEWARE` avec `django_htmx.middleware.HtmxMiddleware`, `CELERY_BROKER_URL = os.environ["REDIS_URL"]`, `CACHES` sur Redis (le throttle et le cache `onlineStatus` en dépendent), `MEDIA_ROOT`/`MEDIA_URL`, `LANGUAGE_CODE = "fr"`, `USE_I18N = True`.

- [ ] **Étape 6 : `clameur/celery.py`**

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clameur.settings")
app = Celery("clameur")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

Et dans `clameur/__init__.py` : `from clameur.celery import app as celery_app` avec `__all__ = ("celery_app",)`. **Cet import est à effet de bord : ne jamais le supprimer, même si un linter le déclare inutilisé.**

- [ ] **Étape 7 : test du socle**

```python
def test_extension_vector_est_disponible(db):
    from django.db import connection
    with connection.cursor() as curseur:
        curseur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert curseur.fetchone() is not None, "extension pgvector absente"
```

L'extension est créée par une migration en tâche 5 ; ce test échoue jusque-là, c'est normal et attendu.

- [ ] **Étape 8 : vérifier**

Lancer : `docker compose up -d db redis && docker compose run --rm web uv run python manage.py check`
Attendu : `System check identified no issues`.

- [ ] **Étape 9 : point de contrôle** — état vérifiable, ne pas committer.

---

### Tâche 2 : app `bornes`

**Fichiers :**
- Créer : `bornes/__init__.py`, `bornes/models.py`, `bornes/admin.py`, `bornes/apps.py`, `bornes/migrations/0001_initial.py`
- Test : `tests/test_bornes.py`

**Interfaces produites :** `Borne` avec les champs `slug`, `nom`, `numero_serie_imprimante`, `dots_par_ligne`, `active`, `texte_accueil`, `duree_max_secondes`.

- [ ] **Étape 1 : test qui échoue**

```python
import pytest
from bornes.models import Borne

@pytest.mark.django_db
def test_une_borne_a_des_valeurs_par_defaut_utilisables():
    borne = Borne.objects.create(slug="place-du-marche", nom="Place du marché")
    assert borne.dots_par_ligne == 576      # 80 mm
    assert borne.duree_max_secondes == 600  # garde-fou technique
    assert borne.active is True
```

- [ ] **Étape 2 : lancer le test** → `ModuleNotFoundError: bornes`.

- [ ] **Étape 3 : `bornes/models.py`**

```python
from django.db import models
from django.utils.translation import gettext_lazy as _


class Borne(models.Model):
    """Relie une affiche, une imprimante Sunmi et des reglages d'evenement.
    / Links a poster, a Sunmi printer and event settings."""

    slug = models.SlugField(unique=True, verbose_name=_("identifiant d'URL"))
    nom = models.CharField(max_length=200, verbose_name=_("nom"))
    numero_serie_imprimante = models.CharField(
        max_length=100, blank=True, verbose_name=_("numéro de série de l'imprimante"),
        help_text=_("Le SN Sunmi. Ce n'est pas un secret."),
    )
    dots_par_ligne = models.PositiveIntegerField(
        default=576, verbose_name=_("points par ligne"),
        help_text=_("576 pour du 80 mm, 384 pour du 58 mm."),
    )
    active = models.BooleanField(default=True, verbose_name=_("active"))
    texte_accueil = models.TextField(blank=True, verbose_name=_("texte d'accueil"))
    duree_max_secondes = models.PositiveIntegerField(
        default=600, verbose_name=_("durée maximale en secondes"),
        help_text=_("Garde-fou technique cote client. Le serveur accepte au-dela."),
    )

    class Meta:
        verbose_name = _("borne")

    def __str__(self):
        return self.nom
```

- [ ] **Étape 4 : migration et test** — `makemigrations bornes`, puis relancer. Attendu : PASS.
- [ ] **Étape 5 : `bornes/admin.py`** — enregistrer `Borne` avec `list_display = ("nom", "slug", "active", "numero_serie_imprimante")`.
- [ ] **Étape 6 : point de contrôle.**

---

### Tâche 3 : le pilote Sunmi vendorisé et ses quatre corrections

**Fichiers :**
- Créer : `impression/__init__.py`, `impression/sunmi_cloud_printer.py` (copié depuis `/home/jonas/TiBillet/dev/LaBoutik/epsonprinter/sunmi_cloud_printer.py`)
- Test : `tests/test_pilote_sunmi.py`

**Interfaces produites :** `SunmiCloudPrinter(dots_per_line, app_id, app_key, printer_sn)` avec `appendText`, `appendQRcode`, `appendImage`, `setAlignment`, `cutPaper`, `orderData`, `pushContent`, `onlineStatus`, `printStatus`.

- [ ] **Étape 1 : copier le pilote tel quel.** Ne rien réécrire : 824 lignes d'ESC/POS éprouvé.

- [ ] **Étape 2 : test de la signature (vecteur figé)**

```python
import hashlib, hmac
from impression.sunmi_cloud_printer import SunmiCloudPrinter

def test_la_signature_hmac_est_conforme():
    pilote = SunmiCloudPrinter(576, app_id="a", app_key="k", printer_sn="SN")
    signature = pilote.generateSign(body='{"x":1}', timestamp="1700000000", nonce="000042")
    attendu = hmac.new(
        key=b"k", msg=b'{"x":1}a1700000000000042', digestmod=hashlib.sha256
    ).hexdigest()
    assert signature == attendu
```

- [ ] **Étape 3 : lancer** → PASS si la copie est fidèle. Si FAIL, la copie est corrompue : recommencer l'étape 1.

- [ ] **Étape 4 : les quatre corrections**

1. `requests.post(...)` → ajouter `timeout=10`. **C'est la correction critique** : sans elle, un worker Celery se bloque indéfiniment.
2. Le `print(json.loads(response.text))` de `httpPost` → `logger.info(...)`, avec `logger = logging.getLogger(__name__)` en tête de module.
3. `httpPost` doit contrôler le retour : lever une exception si `response.status_code != 200`, et retourner le JSON parsé.
4. `onlineStatus`, `printStatus`, `clearPrintJob`, `pushContent` doivent **retourner** ce que rend `httpPost` — aujourd'hui elles ne retournent rien, ce qui rend le contrôle d'état de la spec §6 irréalisable.

- [ ] **Étape 5 : test des corrections**

```python
from unittest.mock import patch
from impression.sunmi_cloud_printer import SunmiCloudPrinter

def test_les_appels_reseau_ont_un_timeout_et_retournent_le_json():
    pilote = SunmiCloudPrinter(576, app_id="a", app_key="k", printer_sn="SN")
    with patch("impression.sunmi_cloud_printer.requests.post") as faux_post:
        faux_post.return_value.status_code = 200
        faux_post.return_value.text = '{"code": 1, "data": {"status": "online"}}'
        resultat = pilote.onlineStatus("SN")
    assert faux_post.call_args.kwargs["timeout"] > 0, "appel sans timeout"
    assert resultat["data"]["status"] == "online"
```

- [ ] **Étape 6 : lancer** → PASS.
- [ ] **Étape 7 : point de contrôle.**

---

### Tâche 4 : backends d'impression (Strategy + mock lisible)

**Fichiers :**
- Créer : `impression/base.py`, `impression/escpos_builder.py`, `impression/mock.py`, `impression/sunmi_cloud.py`
- Test : `tests/test_impression.py`

**Interfaces consommées :** `SunmiCloudPrinter` (tâche 3), `Borne` (tâche 2).
**Interfaces produites :** `PrinterBackend` avec `can_print() -> (bool, str)` et `print_ticket(capsule) -> str` ; `construire_le_ticket(capsule, dots_par_ligne) -> bytes` ; `decoder_escpos(octets) -> list[str]`.

- [ ] **Étape 1 : test du mock, qui est le vrai test de bout en bout**

```python
from impression.escpos_builder import construire_le_ticket
from impression.mock import decoder_escpos

def test_le_ticket_contient_le_pseudo_et_l_url(capsule_factice):
    octets = construire_le_ticket(capsule_factice, dots_par_ligne=576)
    lignes = decoder_escpos(octets)
    texte = "\n".join(lignes)
    assert "anonyme" in texte
    assert str(capsule_factice.uuid) in texte
```

`capsule_factice` : une fixture minimale avec `uuid`, `pseudo="anonyme"`, `duree_secondes=42`, `photo=None`. La définir dans `tests/conftest.py`.

- [ ] **Étape 2 : lancer** → `ModuleNotFoundError`.

- [ ] **Étape 3 : `impression/base.py`**

```python
class PrinterBackend:
    """Interface des backends d'impression (pattern Strategy).
    Pas d'ABC ni de metaclasse : une simple classe, c'est plus lisible.
    / Printing backend interface. No ABC: a plain class is more readable."""

    def can_print(self) -> tuple[bool, str]:
        """Verifie les preconditions AVANT d'essayer d'imprimer.
        :return: (possible, message d'erreur si impossible)"""
        raise NotImplementedError

    def print_ticket(self, capsule) -> str:
        """Imprime et rend le trade_no Sunmi.
        / Prints and returns the Sunmi trade_no."""
        raise NotImplementedError
```

- [ ] **Étape 4 : `impression/escpos_builder.py`**

`construire_le_ticket(capsule, dots_par_ligne)` instancie un `SunmiCloudPrinter` en mode constructeur seul (`app_id="builder"`, `app_key="builder"`, `printer_sn="builder"` — accepté car `httpPost` n'est jamais appelé), puis, dans l'ordre : photo tramée si présente, phrase amorce, QR, ligne d'identité, `cutPaper`. Rendre `printer.orderData`.

**Le tramage doit être explicite :** `appendImage(chemin, mode=SunmiCloudPrinter.DIFFUSE_DITHER, width=...)`. Le défaut du pilote est le seuillage, qui sort une photo en aplats noirs illisibles.

- [ ] **Étape 5 : `impression/mock.py`** — `decoder_escpos(octets)` retire les séquences de contrôle et rend les lignes UTF-8 lisibles, en remplaçant le bloc QR par `[QR CODE: <url>]`. `MockBackend.print_ticket` construit les **mêmes** octets que le backend réel, les décode et les journalise dans un cadre ASCII.

- [ ] **Étape 6 : lancer le test** → PASS.

- [ ] **Étape 7 : `impression/sunmi_cloud.py`**

```python
class SunmiCloudBackend(PrinterBackend):
    def __init__(self, borne):
        self.borne = borne

    def can_print(self) -> tuple[bool, str]:
        if not self.borne.numero_serie_imprimante:
            return False, "Numéro de série Sunmi manquant sur la borne."
        if not os.environ.get("SUNMI_APP_ID"):
            return False, "SUNMI_APP_ID non configuré."
        if not os.environ.get("SUNMI_APP_KEY"):
            return False, "SUNMI_APP_KEY non configuré."
        return True, ""
```

`print_ticket` : construit les octets, charge le buffer, appelle `pushContent(trade_no=f"{sn}_{int(time.time())}", ...)`, rend le `trade_no`.

- [ ] **Étape 8 : test de `can_print`**

```python
@pytest.mark.django_db
def test_can_print_refuse_une_borne_sans_numero_de_serie(monkeypatch):
    monkeypatch.setenv("SUNMI_APP_ID", "a")
    monkeypatch.setenv("SUNMI_APP_KEY", "k")
    borne = Borne.objects.create(slug="b", nom="B", numero_serie_imprimante="")
    possible, message = SunmiCloudBackend(borne).can_print()
    assert possible is False
    assert "série" in message
```

- [ ] **Étape 9 : lancer** → PASS. **Point de contrôle.**

---

### Tâche 5 : app `capsules` — modèles

**Fichiers :**
- Créer : `capsules/__init__.py`, `capsules/models.py`, `capsules/admin.py`, `capsules/apps.py`, `capsules/migrations/0001_initial.py`
- Test : `tests/test_capsules_modeles.py`

**Interfaces produites :** `Capsule`, `Tag`, `TagDeCapsule` selon la spec §5.

- [ ] **Étape 1 : test qui échoue**

```python
@pytest.mark.django_db
def test_l_uuid_est_la_cle_publique_et_n_est_pas_devinable():
    a = Capsule.objects.create(borne=borne)
    b = Capsule.objects.create(borne=borne)
    assert a.uuid != b.uuid
    assert len(str(a.uuid)) == 36

@pytest.mark.django_db
def test_un_tag_garde_la_trace_de_son_origine():
    capsule = Capsule.objects.create(borne=borne)
    tag = Tag.objects.create(nom="mémoire")
    TagDeCapsule.objects.create(capsule=capsule, tag=tag, origine=TagDeCapsule.AUTEUR)
    assert capsule.tags_de_capsule.get().origine == "auteur"
```

- [ ] **Étape 2 : lancer** → échec.

- [ ] **Étape 3 : la migration d'extension, en premier**

`capsules/migrations/0001_initial.py` doit commencer par `pgvector.django.VectorExtension()` dans ses opérations, **avant** la création des tables : sans l'extension, le `VectorField` ne peut pas être créé.

- [ ] **Étape 4 : `capsules/models.py`** — les champs exacts de la spec §5. Points d'attention :
  - `uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False)`
  - `embedding = VectorField(dimensions=1024, null=True, blank=True)` — 1024, pas autre chose
  - `audio_diffusion` : `blank=True`, il n'existe pas avant la publication
  - `statut` : `brouillon` / `publiee` / `retiree`
  - `TagDeCapsule.origine` : choix `auteur` / `machine`, `related_name="tags_de_capsule"`

- [ ] **Étape 5 : migrer, lancer les tests des tâches 1 et 5** → le test `test_extension_vector_est_disponible` passe maintenant.
- [ ] **Étape 6 : `capsules/admin.py`** — c'est **la console** de la spec §11. Actions : retirer/republier une capsule, rejouer chaque tâche d'enrichissement.
- [ ] **Étape 7 : point de contrôle.**

---

### Tâche 6 : capture — `/b/<slug>`

**Fichiers :**
- Créer : `capsules/views.py`, `capsules/urls.py`, `capsules/templates/capsules/borne.html`, `capsules/static/capsules/enregistreur.js`
- Test : `tests/test_capture.py`

**Interfaces consommées :** `Borne`, `Capsule`, `SunmiCloudBackend.can_print`.
**Interfaces produites :** vues `accueil_borne(request, slug)` et `creer_capsule(request, slug)`.

- [ ] **Étape 1 : test de l'état imprimante mis en cache**

```python
@pytest.mark.django_db
def test_l_accueil_signale_une_imprimante_hors_ligne(client, borne, monkeypatch):
    monkeypatch.setattr(
        "capsules.views.interroger_l_imprimante",
        lambda borne: {"en_ligne": False, "message": "hors ligne"},
    )
    reponse = client.get(f"/b/{borne.slug}")
    assert "hors ligne" in reponse.content.decode()
```

- [ ] **Étape 2 : lancer** → 404, la route n'existe pas.

- [ ] **Étape 3 : `interroger_l_imprimante(borne)`** dans `capsules/views.py` : appelle `onlineStatus`, met le résultat en cache **30 secondes** sous la clé `imprimante:<slug>`. Sans ce cache, chaque visiteur taperait l'API Sunmi.

- [ ] **Étape 4 : la vue d'accueil** rend `texte_accueil`, le bouton d'enregistrement et `duree_max_secondes` dans un `data-` attribut lu par le JS.

- [ ] **Étape 5 : `enregistreur.js`** — JS vanilla, sans dépendance.

```javascript
// On accepte ce que le navigateur produit : webm/opus (Chrome, Android),
// mp4/aac (iOS), ogg/opus (Firefox). Aucune liste blanche : elle rejetterait
// un navigateur minoritaire sans que personne s'en apercoive.
let enregistreur = null;
let morceaux = [];
let blobLocal = null;

async function demarrerEnregistrement(dureeMaxSecondes) {
  const flux = await navigator.mediaDevices.getUserMedia({ audio: true });
  enregistreur = new MediaRecorder(flux);
  morceaux = [];
  enregistreur.ondataavailable = (e) => morceaux.push(e.data);
  enregistreur.onstop = () => {
    blobLocal = new Blob(morceaux, { type: enregistreur.mimeType });
    // La reecoute se fait sur le blob LOCAL : instantane, et sans reseau.
    document.getElementById("reecoute").src = URL.createObjectURL(blobLocal);
    envoyerLAudio(blobLocal);
  };
  enregistreur.start();
  // Garde-fou technique : le client arrete, le serveur accepte au-dela.
  setTimeout(() => { if (enregistreur.state === "recording") arreter(); },
             dureeMaxSecondes * 1000);
}
```

`envoyerLAudio` fait le POST **dès l'arrêt**, avant la saisie du pseudo : cela met à profit le temps de frappe et garantit qu'un audio n'est jamais perdu. En cas d'échec : bouton « réessayer », blob conservé, **aucun réessai automatique silencieux**.

- [ ] **Étape 6 : `creer_capsule`** — crée une `Capsule(statut=brouillon)` avec `audio_original`, rend l'`uuid`.

- [ ] **Étape 7 : test de bout en bout de la création**

```python
@pytest.mark.django_db
def test_un_audio_de_n_importe_quel_format_est_accepte(client, borne):
    for nom, type_mime in [("a.webm", "audio/webm"), ("a.m4a", "audio/mp4"), ("a.ogg", "audio/ogg")]:
        fichier = SimpleUploadedFile(nom, b"octets", content_type=type_mime)
        reponse = client.post(f"/b/{borne.slug}/capsule", {"audio": fichier})
        assert reponse.status_code == 200, f"{type_mime} rejeté"
```

- [ ] **Étape 8 : lancer** → PASS. **Point de contrôle.**

---

### Tâche 7 : publication — les trois invariants

**C'est la tâche la plus importante du plan.**

**Fichiers :**
- Créer : `capsules/publication.py`, `capsules/photos.py`, `impression/models.py`, `impression/tasks.py`
- Modifier : `capsules/views.py`
- Test : `tests/test_invariants.py`

**Interfaces produites :** `publier(capsule) -> None`, `normaliser_l_audio(capsule) -> None`, `purger_les_exif(fichier) -> File`, `JobImpression`.

- [ ] **Étape 1 : les tests des invariants, d'abord**

```python
@pytest.mark.django_db
def test_I1_une_capsule_publiee_est_lisible_par_tous_les_navigateurs(capsule_webm):
    publier(capsule_webm)
    capsule_webm.refresh_from_db()
    assert capsule_webm.statut == "publiee"
    assert capsule_webm.audio_diffusion, "pas d'AAC : illisible sur iPhone"
    assert capsule_webm.audio_diffusion.name.endswith(".m4a")

@pytest.mark.django_db
def test_I2_la_publication_survit_a_un_redis_mort(capsule_webm, monkeypatch):
    def redis_mort(*a, **k):
        raise ConnectionError("Redis est mort")
    monkeypatch.setattr("impression.tasks.envoyer_le_ticket.delay", redis_mort)
    monkeypatch.setattr("capsules.tasks.transcrire.delay", redis_mort)
    publier(capsule_webm)          # ne doit pas lever
    capsule_webm.refresh_from_db()
    assert capsule_webm.statut == "publiee"
    assert JobImpression.objects.get(capsule=capsule_webm).statut == "en_attente"

@pytest.mark.django_db
def test_I3_la_publication_survit_a_une_imprimante_absente(capsule_webm, borne_sans_sn):
    capsule_webm.borne = borne_sans_sn
    publier(capsule_webm)
    capsule_webm.refresh_from_db()
    assert capsule_webm.statut == "publiee"
```

- [ ] **Étape 2 : lancer** → les trois échouent.

- [ ] **Étape 3 : `normaliser_l_audio`** — `ffmpeg -i <original> -c:a aac -b:a 64k -ac 1 <sortie>.m4a`, via `subprocess.run(..., timeout=120, check=True)`. En cas d'échec : journaliser dans `erreur_enrichissement`, **ne pas lever** — publier ne doit jamais échouer.

- [ ] **Étape 4 : `publier(capsule)`**, dans cet ordre exact :

```python
def publier(capsule):
    normaliser_l_audio(capsule)          # SYNCHRONE : sans AAC, muet sur iPhone
    capsule.statut = "publiee"
    capsule.publiee_le = timezone.now()
    capsule.save()                       # la base est la source de verite
    job = JobImpression.objects.create(capsule=capsule, borne=capsule.borne)
    # L'enqueue peut echouer : Redis n'est pas une dependance de la publication.
    for envoi in (lambda: envoyer_le_ticket.delay(job.pk),
                  lambda: transcrire.delay(capsule.pk)):
        try:
            envoi()
        except Exception:
            logger.exception("enqueue impossible, relance depuis la console")
```

- [ ] **Étape 5 : lancer les trois tests** → PASS.

- [ ] **Étape 6 : test puis implémentation de la purge EXIF**

```python
def test_les_coordonnees_gps_disparaissent_de_la_photo(photo_avec_gps):
    resultat = purger_les_exif(photo_avec_gps)
    assert Image.open(resultat).getexif().get(0x8825) is None  # GPSInfo
```

`purger_les_exif` : ouvre avec Pillow, applique `ImageOps.exif_transpose` (sinon la photo sort de travers), recrée une image sans métadonnées, sauvegarde. **Sans cette purge, une photo géolocalise la borne et parfois son auteur** — ce qui contredirait la promesse de la spec §2.

- [ ] **Étape 7 : lancer** → PASS. **Point de contrôle.**

---

### Tâche 8 : page de lecture — `/c/<uuid>`

**Fichiers :**
- Créer : `capsules/templates/capsules/capsule.html`, `capsules/templates/mentions_legales.html`
- Modifier : `capsules/views.py`, `capsules/urls.py`
- Test : `tests/test_lecture.py`

- [ ] **Étape 1 : test des trois statuts**

```python
@pytest.mark.django_db
def test_une_capsule_retiree_explique_au_lieu_de_renvoyer_404(client, capsule):
    capsule.statut = "retiree"; capsule.save()
    reponse = client.get(f"/c/{capsule.uuid}")
    assert reponse.status_code == 200          # le ticket est dans la rue
    assert "retirée" in reponse.content.decode()

@pytest.mark.django_db
def test_un_brouillon_est_introuvable(client, capsule):
    assert client.get(f"/c/{capsule.uuid}").status_code == 404
```

- [ ] **Étape 2 : lancer** → échec.
- [ ] **Étape 3 : la vue** — `publiee` → page normale ; `retiree` → 200 avec message sobre ; `brouillon` → 404.
- [ ] **Étape 4 : le template.** Un seul bouton play occupant l'écran, la photo en fond, pseudo, tags, durée annoncée. **Ne pas tenter d'autoplay** : iOS et Android le bloquent sans interaction, c'est sans dérogation. Transcription colorée par locuteur quand elle existe, absente sinon. Lien discret vers `/mentions-legales`.
- [ ] **Étape 5 : `POST /c/<uuid>/ecoute`** incrémente `nombre_ecoutes`, appelé **au clic play**, jamais au chargement.
- [ ] **Étape 6 : lancer** → PASS. **Point de contrôle.**

---

### Tâche 9 : enrichissement Mistral

**Fichiers :**
- Créer : `capsules/tasks.py`, `capsules/transcription.py`
- Test : `tests/test_enrichissement.py`

- [ ] **Étape 1 : test avec Mistral mocké**

```python
@pytest.mark.django_db
def test_la_transcription_conserve_les_locuteurs(capsule_publiee, mistral_mock):
    transcrire(capsule_publiee.pk)
    capsule_publiee.refresh_from_db()
    segments = capsule_publiee.transcription_raw["segments"]
    assert {s["speaker"] for s in segments} == {"speaker_0", "speaker_1"}

@pytest.mark.django_db
def test_un_echec_mistral_ne_depublie_pas_la_capsule(capsule_publiee, mistral_en_panne):
    transcrire(capsule_publiee.pk)
    capsule_publiee.refresh_from_db()
    assert capsule_publiee.statut == "publiee"
    assert capsule_publiee.erreur_enrichissement != ""
```

- [ ] **Étape 2 : lancer** → échec.

- [ ] **Étape 3 : `capsules/transcription.py`**

Trois contraintes de l'API Mistral, apprises en production sur Hypostasia — les violer coûte du temps :

```python
# 1. diarize=True EXIGE timestamp_granularities=["segment"]
# 2. language est INCOMPATIBLE avec timestamp_granularities : puisqu'on
#    diarise, on ne peut pas forcer la langue. Detection auto obligatoire.
# 3. La cle vit dans l'environnement, jamais en base.
parametres = {
    "model": "voxtral-mini-latest",
    "diarize": True,
    "timestamp_granularities": ["segment"],
}
with open(chemin, "rb") as fichier:
    reponse = client.audio.transcriptions.complete(
        file={"content": fichier, "file_name": Path(chemin).name}, **parametres
    )
```

- [ ] **Étape 4 : les trois tâches** — `transcrire`, puis `taguer` (Mistral small → `TagDeCapsule(origine="machine")`), puis `embarquer` (`mistral-embed`, **1024 dimensions**). Chacune : idempotente, rejouable, et **capture ses exceptions dans `erreur_enrichissement` sans jamais dépublier**.
- [ ] **Étape 5 : lancer** → PASS. **Point de contrôle.**

---

### Tâche 10 : throttle et purge

**Fichiers :** modifier `capsules/views.py` ; créer `capsules/management/commands/purger_les_brouillons.py`
**Test :** `tests/test_garde_fous.py`

- [ ] **Étape 1 : test du throttle**

```python
@pytest.mark.django_db
def test_on_ne_peut_pas_vider_le_rouleau_de_papier(client, borne):
    for _ in range(5):
        client.post(f"/b/{borne.slug}/capsule", {"audio": un_fichier()})
    derniere = client.post(f"/b/{borne.slug}/capsule", {"audio": un_fichier()})
    assert derniere.status_code == 429
```

- [ ] **Étape 2 : lancer** → échec.
- [ ] **Étape 3 : throttle par IP et session via le cache Django** sur la création et la publication. Le QR de l'affiche se photographie : sans garde-fou, quelqu'un fait cracher des tickets en continu.
- [ ] **Étape 4 : `purger_les_brouillons`** — supprime les `brouillon` de plus de 24 h, avec leurs fichiers. Commande de gestion lancée par l'opérateur en fin d'événement, **pas de tâche périodique**.
- [ ] **Étape 5 : lancer la suite complète** → tout PASS. **Point de contrôle.**

---

## Vérification finale

1. `docker compose up` — les quatre services démarrent.
2. Suite complète verte.
3. **Vérification navigateur** (skill `claude-in-chrome`) : parcours réel sur `/b/<slug>`, autorisation micro, enregistrement, réécoute, publication, puis `/c/<uuid>` — bouton play, lecture effective, transcription affichée.
4. **Vérification matérielle**, à faire par le mainteneur : imprimer un ticket avec un QR figé sur la vraie NT311, et confirmer `dots_par_ligne` (576 attendu, le README de LaBoutik annonce 384 mais ses tests utilisent 576).
