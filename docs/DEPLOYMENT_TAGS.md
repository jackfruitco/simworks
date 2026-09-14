# Deployment tags

This repository publishes a single runtime image to GHCR:

- `ghcr.io/jackfruitco/simworks`

All runtime services (server, celery worker, celery beat) deploy from that same image and override startup command where needed.

## Tag strategy

- `sha-<gitsha>` - immutable source commit tag built by `cd-staging`
- `staging` - mutable staging pointer tag
- `vX.Y.Z` - immutable release tag promoted by `cd-release`
- `stable` - mutable production pointer tag

## Workflow mapping

- **cd-staging**
  - Triggered by `push` to `main`
  - Builds once and pushes: `sha-<gitsha>`, `staging`
  - Applies image security scan, SBOM generation, provenance attestation, and keyless signing
  - Uses GitHub `staging` environment and deployment metadata
  - Triggers the Dockhand staging Git-stack webhook using environment-scoped `DOCKHAND_WEBHOOK_URL` and `DOCKHAND_WEBHOOK_SECRET` secrets
- **cd-release**
  - Triggered by `release.published` and optional `workflow_dispatch`
  - Rejects prerelease publication events
  - For manual dispatch, requires an existing GitHub Release for the tag and rejects draft/prerelease releases
  - Requires release tag format `vX.Y.Z`
  - Validates release tag version matches `pyproject.toml` at the tagged commit
  - Promotes an already-built immutable digest (prefers `sha-<commit>`, falls back to existing `vX.Y.Z`) to: `vX.Y.Z`, `stable`
  - Verifies signature and provenance only from `cd-staging.yml@refs/heads/main`
  - Uses GitHub `production` environment and deployment metadata
  - Optionally triggers Portainer production webhook

## Deployment settings

- Staging stacks **must** set `SERVER_IMAGE_TAG=staging`.
- Production stacks should set `SERVER_IMAGE_TAG=stable`.
- The compose default `SERVER_IMAGE_TAG=stable` is production-oriented; it is unsafe for staging unless explicitly overridden.
- Configure staging stack image tag as `:staging`
- Configure production stack image tag as `:stable`
- Configure these environment-scoped Action secrets for the `staging` environment:
  - `DOCKHAND_WEBHOOK_URL`: the Dockhand Git-stack webhook URL (`https://dockhand.jackfruit.me/api/git/stacks/<STACK_ID>/webhook`)
  - `DOCKHAND_WEBHOOK_SECRET`: the Dockhand webhook signing secret
- Configure the Dockhand staging Git stack to enable both **Re-pull images** and **Force redeployment**. Re-pulling fetches the rebuilt mutable `:staging` image, while force redeployment handles webhook runs where the Git commit has not changed.
- Configure environment-scoped Action secret `PORTAINER_WEBHOOK`:
  - `production` environment: production stack webhook URL

## Migration notes

- For the Dockhand staging Git stack, explicitly set `SERVER_IMAGE_TAG=staging`. Do not rely on compose defaults.
- Replace any production stack use of `:prod` with `:stable`.
- If your stack currently relies on `:latest`, switch to explicit tags (`:staging` or `:stable`).
- `cd-promote` is removed; release publication now triggers production deployment.
