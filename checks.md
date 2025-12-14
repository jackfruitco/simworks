### Docker build checks

#### Build
- `docker compose -f docker/compose.dev.yaml build --no-cache`

#### Django checks
- `docker compose -f docker/compose.dev.yaml run --rm server python manage.py check --deploy`
- `docker run --rm -it --env-file docker/.env docker-server python manage.py check --deploy`

#### Simcore checks
- `docker compose -f docker/compose.dev.yaml run --rm server python manage.py ai_healthcheck`
- `docker run --rm -it --env-file docker/.env docker-server python manage.py ai_healthcheck`

#### Multiline Build & Check
```aiignore
docker compose -f docker/compose.dev.yaml build --no-cache
docker compose -f docker/compose.dev.yaml run --rm server python manage.py check --deploy
docker compose -f docker/compose.dev.yaml run --rm server python manage.py ai_healthcheck
```

#### Run
- `docker compose -f docker/compose.dev.yaml up`

#### Tests and coverage
- `uv run pytest`
  - Generates `coverage.xml` and a terminal summary via pytest-cov.
  - Fails if overall coverage drops below 80%.