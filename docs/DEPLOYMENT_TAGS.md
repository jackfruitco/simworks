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

- **Release RC (build + tag staging)**
  - Builds once and pushes: `vX.Y.Z-rcN`, `sha-<gitsha>`, `staging`
- **Promote to Prod (retag by digest)**
  - Resolves digest from `vX.Y.Z-rcN`
  - Retags the exact digest to: `vX.Y.Z`, `prod`

## Portainer stack guidance

- Configure staging stack image tag as `:staging`
- Configure prod stack image tag as `:prod`
- If using webhooks, set optional Action secrets:
  - `PORTAINER_WEBHOOK_STAGING`
  - `PORTAINER_WEBHOOK_PROD`
