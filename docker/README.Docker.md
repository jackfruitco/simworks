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

#### Production / CI

- Tailwind is built deterministically in the image build via `docker/Dockerfile.prod`.
- Build pipeline runs `npm ci` and `npm run build:css` in an assets stage, then copies
  `SimWorks/static/css/tailwind.css` into the runtime image before Django collectstatic.
- CI (`.github/workflows/ci.yml`) also runs:
  - `npm ci`
  - `npm run build:css`
  - `git diff --exit-code -- SimWorks/static/css/tailwind.css`
  to ensure committed CSS matches source.

#### Development (without rebuilding image each code change)

- `docker/compose.dev.yaml` mounts `../SimWorks:/app/SimWorks` into the `server` container.
- `docker/entrypoint.sh` is shared by dev/prod and conditionally runs startup tasks (`collectstatic`, `migrate`, role seeding) based on `DJANGO_*` flags.
- `tailwind-watch` service runs `npm run watch:css:docker` and writes directly to
  `/app/static/css/tailwind.css` (the shared static volume served by nginx).
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

If needed, run manually in the running container:

```bash
docker compose -f docker/compose.dev.yaml exec server npm run build:css
docker compose -f docker/compose.dev.yaml exec server python manage.py collectstatic --noinput
```

### References
* [Docker's Python guide](https://docs.docker.com/language/python/)
