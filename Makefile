# Raccourcis de developpement de Clameur.
# / Clameur development shortcuts.
#
# TOUT PASSE PAR DOCKER, et ce n'est pas un detail : ni ffmpeg, ni Python, ni
# PostgreSQL ne sont requis sur le poste. Docker est le seul prerequis.
# / Everything runs in Docker: no ffmpeg, no Python, no PostgreSQL on the host.

COMPOSE = docker compose

# Les binaires du venv sont dans le PATH de l'image : on appelle `python`
# directement, sans passer par `uv run`. Le wrapper `uv` laisse un process
# vivant entre nous et le programme reel — c'est pour la meme raison que
# supervisord.conf n'en utilise nulle part en production.
# / venv binaries are on PATH: call python directly, no uv wrapper.
DANS_WEB = $(COMPOSE) run --rm web python manage.py

# `--user` : sans lui, le conteneur ecrit en root et les fichiers qu'il touche
# sur le disque de l'hote (uv.lock, migrations) deviennent inaccessibles.
# / Without --user the container writes as root onto the host's disk.
COMME_MOI = $(COMPOSE) run --rm --user "$$(id -u):$$(id -g)" -e HOME=/tmp -e UV_CACHE_DIR=/tmp/cache-uv

services:
	$(COMPOSE) up -d db redis

migrate: services
	$(DANS_WEB) migrate

# Cent clameurs ecoutables, taguees, illustrees et groupees par theme,
# puis le serveur en mode DEBUG.
# / A hundred audible, tagged, illustrated, theme-clustered clameurs.
fixture: migrate
	$(DANS_WEB) creer_des_clameurs --nombre 100 --vider
	$(DANS_WEB) projeter_la_constellation
	@echo ""
	@echo "  Constellation : http://localhost:8000/"
	@echo "  Borne         : http://localhost:8000/b/place-du-marche"
	@echo "  Affiche       : http://localhost:8000/b/place-du-marche/affiche  (staff)"
	@echo "  Console       : http://localhost:8000/admin/"
	@echo ""
	$(MAKE) run

# A relancer apres chaque vague d'enrichissement : une projection est globale,
# une nouvelle clameur deplace toutes les autres.
# / Rerun after each enrichment wave: a projection is global.
constellation:
	$(DANS_WEB) projeter_la_constellation

run: services
	DEBUG=true $(COMPOSE) up web celery

test: services
	$(COMPOSE) run --rm web pytest -q

# Apres l'ajout d'une dependance. `uv lock` D'ABORD, car le Dockerfile fait
# `uv sync --frozen` et installerait sinon l'ancien jeu, en silence. Et un
# `build` seul ne suffit pas : les conteneurs deja lances continuent de
# tourner sur l'ancienne image.
# / uv lock first (--frozen ignores pyproject), then recreate: build alone is
#   not enough.
# `build` SANS ARGUMENT : chaque service qui declare `build: .` a sa propre
# image. N'en reconstruire qu'une laissait l'autre sur une version anterieure,
# avec un PATH different — et un worker Celery qui ne trouvait plus son binaire.
# / Each service with `build: .` has its own image; building only one left the
#   other behind, with a stale PATH.
rebuild:
	$(COMME_MOI) --entrypoint uv web lock
	$(COMPOSE) build
	$(COMPOSE) up -d --force-recreate web celery

console:
	$(DANS_WEB) createsuperuser

imprimante:
	$(DANS_WEB) tester_l_imprimante place-du-marche

# Les migrations sont ecrites sur le disque de l'hote : identite obligatoire.
# / Migrations land on the host's disk: identity required.
migrations:
	$(COMME_MOI) web python manage.py makemigrations

.PHONY: services migrate fixture constellation run test rebuild console imprimante migrations
