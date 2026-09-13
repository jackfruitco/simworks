### Building and running your application

When you're ready, start your application by running:
`docker compose up --build`.

Your application will be available at http://localhost:8000.

### Deploying your application to the cloud

First, build your image, e.g.: `docker build -t myapp .`.
If your cloud uses a different CPU architecture than your development
machine (e.g., you are on a Mac M1 and your cloud provider is amd64),
you'll want to build the image for that platform, e.g.:
`docker build --platform=linux/amd64 -t myapp .`.

Then, push it to your registry, e.g. `docker push myregistry.com/myapp`.

Consult Docker's [getting started](https://docs.docker.com/go/get-started-sharing/)
docs for more detail on building and pushing.

### Tailwind CSS in Docker

There is no Node toolchain. `django-tailwind-cli` drives the official standalone
Tailwind CSS binary through `manage.py tailwind`.

#### Production / CI

- `docker/Dockerfile.prod` does **not** build CSS. `SimWorks/static/css/tailwind.css`
  is committed, and the runtime stage's `COPY SimWorks /app/SimWorks` brings it in.
  Building in the image would need network access at build time to fetch the
  Tailwind binary and would gain nothing over the committed artifact.
- CI (`.github/workflows/ci.yml`) is what keeps that safe. It runs:
  - `uv run python SimWorks/manage.py tailwind build --force`
  - `git diff --exit-code -- SimWorks/static/css/tailwind.css`
  so a stale committed stylesheet fails the build.

#### Development (without rebuilding image each code change)

- `docker/compose.dev.yaml` mounts `../SimWorks:/app/SimWorks` into the `server` container.
- `docker/entrypoint.sh` is shared by dev/prod and conditionally runs startup tasks (`collectstatic`, `migrate`, role seeding) based on `DJANGO_*` flags.
- `tailwind-watch` runs `manage.py tailwind watch` and writes directly to
  `/app/static/css/tailwind.css` (the shared static volume served by nginx), via
  `TAILWIND_CLI_DIST_CSS=../../static/css/tailwind.css`.
- `docker/Dockerfile.dev` pre-fetches the pinned Tailwind binary into
  `/app/.tailwind-cli` at build time, so the container needs no network on first
  start. That path sits outside `/app/SimWorks` because the bind mount would
  otherwise hide it; `TAILWIND_CLI_PATH` points the watcher at it.
- Defaults in dev compose:
  - `DJANGO_MIGRATE=1`
  - `DJANGO_CREATE_DEFAULT_ROLES=1`
  - `DJANGO_COLLECTSTATIC` unset (skipped unless explicitly set to `1`)

For quick iteration after editing templates/CSS without image rebuild:

```bash
docker compose -f docker/compose.dev.yaml up --build
```

After that, editing HTML templates or Tailwind source should trigger automatic CSS rebuilds.
Refresh the page to see updates; no image rebuild or manual container command needed.

Note that the watcher writes only into the static volume. To refresh the
**committed** `SimWorks/static/css/tailwind.css` that CI checks, run the build on
the host:

```bash
uv run python SimWorks/manage.py tailwind build
```

If needed, run manually in the running container:

```bash
docker compose -f docker/compose.dev.yaml exec server python manage.py tailwind build
docker compose -f docker/compose.dev.yaml exec server python manage.py collectstatic --noinput
```

### References
* [Docker's Python guide](https://docs.docker.com/language/python/)
