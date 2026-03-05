# Deployment tags

This repository publishes a single runtime image to GHCR:

- `ghcr.io/jackfruitco/simworks`

All runtime services (server, celery worker, celery beat) deploy from that same image and override startup command where needed.

## Tag strategy

- `vX.Y.Z-rcN` — immutable release candidate tags (for testing)
- `sha-<gitsha>` — immutable source commit tag
- `staging` — mutable staging pointer tag
- `vX.Y.Z` — immutable final release tag
- `prod` — mutable production pointer tag

## Workflow mapping

- **cd-release**
  - Manual workflow (`workflow_dispatch`)
  - Runs only from `main`
  - Builds once and pushes: `vX.Y.Z-rcN`, `sha-<gitsha>`, `staging`
  - Applies image security checks, SBOM generation, provenance attestation, and keyless signing
  - Optional webhook trigger controlled by `trigger_webhook` input
- **cd-promote**
  - Manual workflow (`workflow_dispatch`)
  - Runs only from `main`
  - Requires `production` environment approval
  - Resolves digest from `vX.Y.Z-rcN`
  - Verifies signature and provenance for the source digest
  - Retags the exact digest to: `vX.Y.Z`, `prod`
  - Optional webhook trigger controlled by `trigger_webhook` input

## Portainer stack guidance

- Configure staging stack image tag as `:staging`
- Configure prod stack image tag as `:prod`
- If using webhooks, set optional Action secrets:
  - `PORTAINER_WEBHOOK_STAGING`
  - `PORTAINER_WEBHOOK_PROD`
