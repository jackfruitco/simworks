DEV_COMPOSE=docker/compose.dev.yaml
PROD_COMPOSE=docker/compose.prod.yaml
DEV_PROFILES ?= core,workers
DEV_UP_FLAGS ?=
PROD_UP_FLAGS ?=

.PHONY: help \
	dev-up dev-up-d dev-up-core dev-up-core-d dev-up-full dev-up-full-d \
	dev-down dev-logs dev-shell dev-chown-vols dev-collectstatic \
	dev-rerun dev-rerun-core dev-rerun-full \
	prod-build prod-up prod-up-d prod-down prod-logs prod-rerun

help:
	@echo "Targets:"
	@echo "  dev-up             Start dev stack (build)"
	@echo "  dev-up-d           Start dev stack detached (build)"
	@echo "  dev-up-core        Start dev core only (no workers)"
	@echo "  dev-up-core-d      Start dev core only detached"
	@echo "  dev-up-full        Start dev core + workers"
	@echo "  dev-up-full-d      Start dev core + workers detached"
	@echo "  dev-rerun          Recreate dev stack (build + force recreate)"
	@echo "  dev-down           Stop dev stack"
	@echo "  dev-logs           Tail dev server logs"
	@echo "  dev-shell          Shell into dev server container"
	@echo "  dev-chown-vols     Fix perms on static/media volumes"
	@echo "  dev-collectstatic  Run collectstatic in dev (writes into volume)"
	@echo "  prod-build         Build prod image"
	@echo "  prod-up            Start prod stack (detached)"
	@echo "  prod-up-d          Alias for prod-up"
	@echo "  prod-rerun         Recreate prod stack (build + force recreate)"
	@echo "  prod-down          Stop prod stack"
	@echo "  prod-logs          Tail prod web logs"

dev-up:
	docker compose -f $(DEV_COMPOSE) --profile $(DEV_PROFILES) up --build $(DEV_UP_FLAGS)

dev-up-d:
	$(MAKE) dev-up DEV_UP_FLAGS="-d"

dev-up-core:
	$(MAKE) dev-up DEV_PROFILES=core

dev-up-core-d:
	$(MAKE) dev-up DEV_PROFILES=core DEV_UP_FLAGS="-d"

dev-up-full:
	$(MAKE) dev-up DEV_PROFILES=core,workers

dev-up-full-d:
	$(MAKE) dev-up DEV_PROFILES=core,workers DEV_UP_FLAGS="-d"

# "rerun" == rebuild + recreate containers (no detach by default)
dev-rerun:
	docker compose -f $(DEV_COMPOSE) --profile $(DEV_PROFILES) up --build --force-recreate

dev-rerun-core:
	$(MAKE) dev-rerun DEV_PROFILES=core

dev-rerun-full:
	$(MAKE) dev-rerun DEV_PROFILES=core,workers

dev-down:
	docker compose -f $(DEV_COMPOSE) down

dev-logs:
	docker compose -f $(DEV_COMPOSE) logs -f --tail=200 server

dev-shell:
	docker compose -f $(DEV_COMPOSE) exec server sh

dev-chown-vols:
	docker compose -f $(DEV_COMPOSE) run --rm --user root server sh -lc 'chown -R 10001:10001 /app/static /app/media && chmod -R u+rwX /app/static /app/media'

dev-collectstatic:
	docker compose -f $(DEV_COMPOSE) exec -e DJANGO_COLLECTSTATIC=1 server sh -lc 'python manage.py collectstatic --noinput --clear'

prod-build:
	docker build -f Dockerfile -t simworks:prod .

prod-up:
	docker compose -f $(PROD_COMPOSE) up -d --build $(PROD_UP_FLAGS)

prod-up-d:
	$(MAKE) prod-up

prod-rerun:
	docker compose -f $(PROD_COMPOSE) up -d --build --force-recreate

prod-down:
	docker compose -f $(PROD_COMPOSE) down

prod-logs:
	docker compose -f $(PROD_COMPOSE) logs -f --tail=200