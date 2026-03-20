# MedSim Privacy Implementation

## Defaults
- Raw AI request/response persistence is disabled by default.
- Provider raw payload persistence is disabled by default.
- Basic PII warning and lightweight scanning are enabled by default.

## User rights
- Authenticated export at `/privacy/export/`.
- Account deletion flow at `/privacy/delete-account/` with explicit confirmation.

## Developer notes
For local debugging only, you can enable raw AI persistence by setting:
- `PRIVACY_PERSIST_RAW_AI_REQUESTS=true`
- `PRIVACY_PERSIST_RAW_AI_RESPONSES=true`
- `PRIVACY_PERSIST_AI_MESSAGE_HISTORY=true`
- `PRIVACY_PERSIST_PROVIDER_RAW=true`

Do not enable these in production unless there is a documented legal basis.
