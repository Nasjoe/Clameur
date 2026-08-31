# Raccourcis de developpement. Les tests tournent en local contre les services
# docker, dont les ports sont decales pour ne pas heurter un postgres du poste.
# / Dev shortcuts: tests run locally against the dockerised services.
LOCAL = POSTGRES_HOST=localhost POSTGRES_PORT=5433 REDIS_URL=redis://localhost:6380/0

services:
	docker compose up -d db redis

test: services
	$(LOCAL) uv run pytest -q

migrate:
	$(LOCAL) uv run python manage.py migrate

# Apres l'ajout d'une dependance : rebuild NE SUFFIT PAS, les conteneurs
# deja lances continuent de tourner sur l'ancienne image.
# / After adding a dependency: rebuild alone is not enough.
# `uv lock` D'ABORD : le Dockerfile fait `uv sync --frozen`, qui installe
# le lock tel quel. Un pyproject modifie sans relock passe donc inapercu.
# / uv lock first: --frozen installs the lock as-is, ignoring pyproject.
rebuild:
	uv lock
	docker compose build web
	docker compose up -d --force-recreate web celery

run: services
	$(LOCAL) uv run python manage.py runserver 0.0.0.0:8000

.PHONY: services test migrate run rebuild
