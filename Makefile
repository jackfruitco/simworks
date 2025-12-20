DEV_COMPOSE=docker/compose.dev.yaml
PROD_COMPOSE=docker/compose.prod.yaml
DEV_PROFILES ?= core,workers

.PHONY: help dev-up dev-down dev-logs dev-shell dev-chown-vols dev-collectstatic prod-build prod-up prod-down prod-logs

help:
	@echo "Targets:"
	@echo "  dev-up             Start dev stack (build)"
	@echo "  dev-down           Stop dev stack"
	@echo "  dev-logs           Tail dev server logs"
	@echo "  dev-shell          Shell into dev server container"
	@echo "  dev-chown-vols     Fix perms on static/media volumes"
	@echo "  dev-collectstatic  Run collectstatic in dev (writes into volume)"
	@echo "  prod-build         Build prod image"
	@echo "  prod-up            Start prod stack"
	@echo "  prod-down          Stop prod stack"
	@echo "  prod-logs          Tail prod web logs"

dev-up:
	docker compose -f $(DEV_COMPOSE) --profile $(DEV_PROFILES) up --build

dev-up-core:
	$(MAKE) dev-up DEV_PROFILES=core

dev-up-full:
	$(MAKE) dev-up DEV_PROFILES=core,workers

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
	docker compose -f $(PROD_COMPOSE) up -d --build

prod-down:
	docker compose -f $(PROD_COMPOSE) down

prod-logs:
	docker compose -f $(PROD_COMPOSE) logs -f --tail=200
