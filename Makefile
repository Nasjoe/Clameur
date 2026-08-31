# Raccourcis de developpement de Clameur.
# / Clameur development shortcuts.
#
# TOUT PASSE PAR DOCKER, et ce n'est pas un detail : ffmpeg n'est pas installe
# sur le poste. Une commande lancee en local echouerait des qu'une capsule doit
# etre normalisee — c'est-a-dire a chaque publication.
# / Everything runs in Docker: ffmpeg is not installed on the host.

COMPOSE = docker compose
DANS_WEB = $(COMPOSE) run --rm web uv run python manage.py

services:
	$(COMPOSE) up -d db redis

migrate: services
	$(DANS_WEB) migrate

# Cent clameurs ecoutables, taguees, illustrees et groupees par theme,
# puis le serveur en mode DEBUG.
# / A hundred audible, tagged, illustrated, theme-clustered clameurs, then the server.
fixture: migrate
	$(DANS_WEB) creer_des_clameurs --nombre 100 --vider
	$(DANS_WEB) projeter_la_constellation
	@echo ""
	@echo "  Constellation : http://localhost:8000/constellation"
	@echo "  Borne   : http://localhost:8000/b/place-du-marche"
	@echo "  Affiche : http://localhost:8000/b/place-du-marche/affiche  (staff)"
	@echo "  Console : http://localhost:8000/admin/"
	@echo ""
	$(MAKE) run

# A relancer apres chaque vague d'enrichissement : une projection est
# globale, une nouvelle clameur deplace toutes les autres.
# / Rerun after each enrichment wave: a projection is global.
constellation:
	$(DANS_WEB) projeter_la_constellation

run: services
	DEBUG=true $(COMPOSE) up web celery

test: services
	$(COMPOSE) run --rm web uv run pytest -q

# Apres l'ajout d'une dependance : `uv lock` D'ABORD, car le Dockerfile fait
# `uv sync --frozen` et installerait sinon l'ancien jeu, en silence. Et un
# `build` seul ne suffit pas : les conteneurs deja lances continuent de
# tourner sur l'ancienne image.
# / uv lock first (--frozen ignores pyproject), and recreate: build alone is not enough.
rebuild:
	uv lock
	$(COMPOSE) build web
	$(COMPOSE) up -d --force-recreate web celery

console:
	$(DANS_WEB) createsuperuser

imprimante:
	$(DANS_WEB) tester_l_imprimante place-du-marche

.PHONY: services migrate fixture run test rebuild console imprimante constellation
