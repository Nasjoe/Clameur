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

# Un `make` nu doit renseigner, pas agir : la premiere cible d'un Makefile est
# celle qui part toute seule, et ce serait la pire des surprises.
# / A bare `make` should inform, not act.
.DEFAULT_GOAL := aide

BLEU  = \033[36m
GRAS  = \033[1m
BRUN  = \033[33m
FIN   = \033[0m

aide:  ## Affiche cette aide
	@printf "\n  $(GRAS)Clameur$(FIN) — capsules sonores, tickets QR, constellation\n"
	@printf "  Docker est le seul prérequis.\n\n"
	@printf "  $(BRUN)Au quotidien$(FIN)\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-z_-]+:.*?## / {printf "    $(BLEU)%-14s$(FIN) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n  $(BRUN)Premiers pas$(FIN)\n"
	@printf "    cp .env.example .env  puis  make fixture\n"
	@printf "    Constellation  http://localhost:8000/\n"
	@printf "    Borne          http://localhost:8000/b/place-du-marche\n"
	@printf "    Console        http://localhost:8000/admin/\n\n"
	@printf "  $(BRUN)Bon à savoir$(FIN)\n"
	@printf "    Sans clé Mistral, les capsules restent publiées et écoutables,\n"
	@printf "    simplement sans transcription. Sans identifiants Sunmi, le ticket\n"
	@printf "    s'écrit dans les journaux — avec les mêmes octets ESC/POS :\n"
	@printf "    $(BLEU)docker compose logs -f celery | grep -A 20 'Ticket (mock)'$(FIN)\n\n"
	@printf "  La mise en production est décrite dans docs/PASSATION-PRODUCTION.md\n\n"

services:  ## Démarre PostgreSQL et Redis seuls
	$(COMPOSE) up -d db redis

migrate: services  ## Applique les migrations
	$(DANS_WEB) migrate

migrations:  ## Génère les migrations (écrit sur ton disque, d'où --user)
	$(COMME_MOI) web python manage.py makemigrations

fixture: migrate  ## Crée 100 clameurs de démonstration, puis lance le serveur
	$(DANS_WEB) creer_des_clameurs --nombre 100 --vider
	$(DANS_WEB) projeter_la_constellation
	@printf "\n  Constellation : http://localhost:8000/\n"
	@printf "  Borne         : http://localhost:8000/b/place-du-marche\n"
	@printf "  Affiche       : http://localhost:8000/b/place-du-marche/affiche  (staff)\n"
	@printf "  Console       : http://localhost:8000/admin/\n\n"
	$(MAKE) run

run: services  ## Lance le serveur et le worker, en mode DEBUG
	DEBUG=true $(COMPOSE) up web celery

test: services  ## Lance toute la suite de tests
	$(COMPOSE) run --rm web pytest -q

lint:  ## Vérifie le style du code
	$(COMPOSE) run --rm web ruff check .

# A relancer apres chaque vague d'enrichissement : une projection est globale,
# une nouvelle clameur deplace toutes les autres.
# / Rerun after each enrichment wave: a projection is global.
constellation:  ## Recalcule la position des étoiles du ciel
	$(DANS_WEB) projeter_la_constellation

console:  ## Crée un compte opérateur pour /admin/
	$(DANS_WEB) createsuperuser

imprimante:  ## Imprime un ticket de test sur la vraie Sunmi
	$(DANS_WEB) tester_l_imprimante place-du-marche

purge:  ## Supprime les enregistrements jamais publiés (annonce seulement)
	$(DANS_WEB) purger_les_brouillons

# `uv lock` D'ABORD, car le Dockerfile fait `uv sync --frozen` et installerait
# sinon l'ancien jeu, en silence. `build` SANS ARGUMENT : chaque service qui
# declare `build: .` a sa propre image, et n'en reconstruire qu'une laissait
# l'autre sur un PATH perime. Enfin, un `build` seul ne suffit pas : les
# conteneurs deja lances continuent de tourner sur l'ancienne image.
# / Lock first, build every image, then recreate: each step is load-bearing.
rebuild:  ## Après ajout d'une dépendance : relock, reconstruit, recrée
	$(COMME_MOI) --entrypoint uv web lock
	$(COMPOSE) build
	$(COMPOSE) up -d --force-recreate web celery

verifier: ## Contrôle la configuration de déploiement (éditeur, contact, https)
	$(COMPOSE) run --rm -e DEBUG=false web python manage.py check --deploy

.PHONY: aide services migrate migrations fixture run test lint constellation \
        console imprimante purge rebuild verifier
