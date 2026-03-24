# Management Commands

## Overview

All project-defined Django management commands are invoked via:

```
uv run python SimWorks/manage.py <command> [options]
```

Commands live in two locations:

- **`SimWorks/apps/<app>/management/commands/`** — app-level commands (accounts, common)
- **`packages/orchestrai_django/src/orchestrai_django/management/commands/`** — OrchestrAI integration commands

Only project-defined commands are documented here. Built-in Django commands (`migrate`, `shell`, `createsuperuser`, etc.) are not covered.

---

## Command Index

| Command | App / Package | Purpose |
|---|---|---|
| [`create_dev_user`](#create_dev_user) | accounts | Create a local dev superuser at `dev@medsim.local` |
| [`dump_users`](#dump_users) | accounts | Export user records (with password hashes) to JSON |
| [`seed_roles`](#seed_roles) | accounts | Seed default `UserRole` records and inactive system users |
| [`restore_users`](#restore_users) | accounts | Restore users from a `dump_users` JSON file |
| [`reset_migrations`](#reset_migrations) | common | ⚠ Delete all migration files (local dev only) |
| [`export_openapi`](#export_openapi) | common | Export the API v1 OpenAPI schema to JSON or YAML |
| [`sim_debug`](#sim_debug) | common | Toggle per-simulation verbose debug logging |
| [`ai_healthcheck`](#ai_healthcheck) | orchestrai_django | Run OrchestrAI healthchecks and report status |
| [`run_service`](#run_service) | orchestrai_django | Execute an OrchestrAI service from the CLI |

---

## `create_dev_user`

### Purpose

Creates a fixed developer superuser (`dev@medsim.local`) for use in local development environments. Requires at least one `UserRole` to exist; uses the lowest-ID role. If the user already exists, the command exits without modifying it.

### Usage

```
uv run python SimWorks/manage.py create_dev_user [--force]
```

### Options

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `-f` / `--force` | flag | `False` | No | Bypass `DJANGO_DEBUG` and `DJANGO_CREATE_DEV_USER` environment checks |

### Environment variables

| Variable | Effect |
|---|---|
| `DJANGO_DEBUG` | Must be `true` (unless `--force`) for the command to run |
| `DJANGO_CREATE_DEV_USER` | Must be `true` (unless `--force`) for the command to run |
| `DJANGO_DEV_USER_PASSWORD` | Password set on creation; defaults to `"dev"` |

### Examples

```bash
# Normal usage — honours env guards
DJANGO_DEBUG=true DJANGO_CREATE_DEV_USER=true uv run python SimWorks/manage.py create_dev_user

# Force creation in any environment (e.g. a docker entrypoint)
uv run python SimWorks/manage.py create_dev_user --force

# Use a custom password
DJANGO_DEV_USER_PASSWORD=supersecret uv run python SimWorks/manage.py create_dev_user --force
```

### Side effects

- Creates one `User` row with `email=dev@medsim.local`, `is_active=True`, `is_staff=True`, `is_superuser=True`, assigned to the first `UserRole` (ordered by `id`).
- Sets the hashed password via `user.set_password()`.
- No-op if the user already exists (existing password is not changed).

### Notes / caveats

- **Environment-gated by default**: both `DJANGO_DEBUG=true` and `DJANGO_CREATE_DEV_USER=true` must be set, or the command silently skips. Use `--force` to bypass in scripts.
- **Requires a UserRole**: if no `UserRole` exists (e.g. migrations not run, or `seed_roles` not run), the command prints an error and exits without creating the user.
- **Safe for local/staging**: designed for dev/staging; do **not** run with `--force` in production.

---

## `dump_users`

### Purpose

Exports user records from the database to a JSON file, preserving hashed passwords and role IDs. Intended as a snapshot/migration tool to move users between environments (pair with [`restore_users`](#restore_users)).

### Usage

```
uv run python SimWorks/manage.py dump_users [--emails addr ...] [--output FILE]
```

### Options

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--emails` | `str` (one or more) | (all users) | No | One or more email addresses to include. If omitted, all users are exported. |
| `--output` | `str` | `users.json` | No | Output file path |

### Examples

```bash
# Dump all users
uv run python SimWorks/manage.py dump_users

# Dump to a custom file
uv run python SimWorks/manage.py dump_users --output /tmp/export.json

# Dump specific users
uv run python SimWorks/manage.py dump_users --emails alice@example.com bob@example.com

# Dump a single user
uv run python SimWorks/manage.py dump_users --emails trainer@medsim.local --output trainer.json
```

### Side effects

- **Writes a file** at the specified `--output` path (default: `users.json` in the current working directory).
- **Exports hashed passwords** — the output file contains `bcrypt`/`argon2` hashes; treat it as sensitive.
- No database writes.

### Notes / caveats

- Output format is a JSON array compatible with `restore_users`.
- If no users match the given emails, the command prints an error and does **not** write a file.
- Role references are stored as integer IDs; IDs may differ between environments. `restore_users` will skip a user if its role ID doesn't exist in the target database.

---

## `seed_roles`

### Purpose

Seeds the initial set of `UserRole` records and their associated inactive system users. Safe to run at any time — it is fully idempotent and skips records that already exist.

### Usage

```
uv run python SimWorks/manage.py seed_roles
```

### Options

None.

### Examples

```bash
# Seed roles on first setup (or after a database reset)
uv run python SimWorks/manage.py seed_roles

# Safe to re-run — only creates missing records
uv run python SimWorks/manage.py seed_roles
```

### Side effects

**System roles and users created** (each with an inactive system user):

| Role | System user email |
|---|---|
| `Sim` | `stitch@simworks.local` |
| `System` | `system@medsim.local` |

System users are created with `is_active=False` and no password set.

**Learner roles created** (no associated user):

- `EMT (NREMT-B)`
- `Paramedic (NRP)`
- `Military Medic`
- `SOF Medic`
- `RN`
- `RN, BSN`
- `Physician`

### Notes / caveats

- Fully idempotent: safe to run in CI, container startup scripts, or after migrations.
- Should be run after initial `migrate` to ensure `create_dev_user` and other commands have a valid role to assign.
- Order of role IDs is not guaranteed; do not hard-code role IDs in fixtures or tests.

---

## `restore_users`

### Purpose

Restores users from a JSON file produced by [`dump_users`](#dump_users), preserving password hashes. Skips users whose email already exists in the database. Assigns each user the role ID from the export; the role must exist in the target database.

### Usage

```
uv run python SimWorks/manage.py restore_users <filepath>
```

### Options

| Argument | Type | Default | Required | Description |
|---|---|---|---|---|
| `filepath` | `str` (positional) | — | **Yes** | Path to a JSON file produced by `dump_users` |

### Examples

```bash
# Restore all users from a dump
uv run python SimWorks/manage.py restore_users users.json

# Restore from a path-qualified dump
uv run python SimWorks/manage.py restore_users /tmp/staging_export.json
```

### Side effects

- Creates new `User` rows with preserved password hashes, metadata, and role assignment.
- **Users are assigned new auto-generated primary keys** — original IDs are not preserved.
- Existing users (matched by email) are skipped with a warning.

### Notes / caveats

- **Role IDs must match**: if the role ID in the export does not exist in the target database, the user is skipped. Run `seed_roles` first if roles may be missing.
- **Fallback to role ID 1**: if the JSON entry has no role field, the command falls back to role ID `1`. If role ID 1 doesn't exist, the user is skipped. This fallback may produce unexpected role assignments; prefer complete exports from `dump_users`.
- Passwords are inserted as raw hashes — no re-hashing occurs. Password formats from different Django versions may be incompatible.
- Not safe to run on production data without verifying role ID alignment between source and target environments.

---

## `reset_migrations`

### Purpose

Deletes all Django migration files (except `__init__.py`) from every app under `SimWorks/apps/`. Optionally regenerates them by running `makemigrations`.

> **⚠ DESTRUCTIVE — local/dev use only.** This permanently deletes migration history. Never run on a shared or production database.

### Usage

```
uv run python SimWorks/manage.py reset_migrations [--makemigrations]
```

### Options

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `-m` / `--makemigrations` | flag | `False` | No | Run `makemigrations` immediately after deleting migration files |

### Examples

```bash
# Delete all migration files
uv run python SimWorks/manage.py reset_migrations

# Delete and regenerate in one step
uv run python SimWorks/manage.py reset_migrations --makemigrations
```

### Side effects

- **Permanently deletes** all `.py` migration files (excluding `__init__.py`) found in any `migrations/` directory under `SimWorks/apps/`.
- With `--makemigrations`: runs `manage.py makemigrations`, producing a single new initial migration per app.
- **No database changes** — this only affects migration files on disk.

### Notes / caveats

- After running, all migration state is lost. The database must be dropped and recreated (`migrate` from scratch) for the new migrations to apply cleanly.
- Scoped to `SimWorks/apps/` — does not affect package-level migrations in `packages/`.
- **Not safe for staging or production**: only use locally or in throwaway containers.

---

## `export_openapi`

### Purpose

Exports the OpenAPI 3.x schema for the MedSim API v1 (`/api/v1/`). Outputs JSON or YAML to a file or stdout. Use this to regenerate `docs/openapi/v1.json` or to produce a schema for external tooling.

### Usage

```
uv run python SimWorks/manage.py export_openapi [--output FILE] [--format {json,yaml}] [--indent N]
```

### Options

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `-o` / `--output` | `str` | (stdout) | No | File path to write. If omitted, schema is printed to stdout. |
| `-f` / `--format` | `json` \| `yaml` | `json` | No | Output format |
| `--indent` | `int` | `2` | No | Indentation spaces for JSON output (ignored for YAML) |

### Examples

```bash
# Print schema to stdout
uv run python SimWorks/manage.py export_openapi

# Update the committed schema file
uv run python SimWorks/manage.py export_openapi --output docs/openapi/v1.json

# YAML format to a file
uv run python SimWorks/manage.py export_openapi --format yaml --output docs/openapi/v1.yaml

# Compact JSON (no indentation)
uv run python SimWorks/manage.py export_openapi --indent 0
```

### Side effects

- Writes a file when `--output` is specified; creates intermediate directories automatically.
- No database writes.

### Notes / caveats

- **YAML requires PyYAML**: if `pyyaml` is not installed, the command raises a `CommandError`. Install with `uv add pyyaml`.
- The schema is generated live from the running code via Django Ninja. Run with the full application stack loaded to capture all routes.
- The committed schema at `docs/openapi/v1.json` should be kept in sync with the codebase using this command.

---

## `sim_debug`

### Purpose

Toggles per-simulation verbose debug logging without changing global log levels. The debug flag is stored in Django cache and expires automatically. When active, AI service calls executed against the simulation emit extra `INFO`-level log lines tagged `[SIM_DEBUG]`.

### Usage

```
uv run python SimWorks/manage.py sim_debug <subcommand> <simulation_id> [options]
```

Subcommands: `enable`, `disable`, `status`

### Options

**`enable`**

| Argument | Type | Default | Required | Description |
|---|---|---|---|---|
| `simulation_id` | `int` (positional) | — | **Yes** | Database ID of the simulation |
| `--ttl` | `int` | `3600` | No | Cache TTL in seconds (default: 1 hour) |

**`disable`**

| Argument | Type | Default | Required | Description |
|---|---|---|---|---|
| `simulation_id` | `int` (positional) | — | **Yes** | Database ID of the simulation |

**`status`**

| Argument | Type | Default | Required | Description |
|---|---|---|---|---|
| `simulation_id` | `int` (positional) | — | **Yes** | Database ID of the simulation |

### Examples

```bash
# Enable debug logging for simulation 42 (default 1-hour TTL)
uv run python SimWorks/manage.py sim_debug enable 42

# Enable with a 5-minute TTL
uv run python SimWorks/manage.py sim_debug enable 42 --ttl 300

# Disable immediately
uv run python SimWorks/manage.py sim_debug disable 42

# Check current state
uv run python SimWorks/manage.py sim_debug status 42
```

### Side effects

- **`enable`**: writes a cache entry at key `orca:sim_debug:<simulation_id>` with the given TTL.
- **`disable`**: deletes the cache entry immediately.
- **`status`**: read-only; no side effects.
- No database writes for any subcommand.

### Notes / caveats

- The flag lives in **Django cache**, not the database. It is lost on cache flush or restart (depending on cache backend).
- Works across multiple worker processes as long as they share the same cache backend.
- The simulation does **not** need to be active or exist in the database — the flag is keyed on the integer ID only.
- Safe for local, staging, and production use. Enabling on production generates additional log volume; use short TTLs.

---

## `ai_healthcheck`

### Purpose

Runs OrchestrAI healthchecks and reports results. Designed for CI pipelines and container readiness/liveness probes. Exits non-zero on failure.

### Usage

```
uv run python SimWorks/manage.py ai_healthcheck [--json]
```

### Options

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--json` | flag | `False` | No | Emit results as JSON (includes `http_status` field for CI parsing) |

### Examples

```bash
# Human-readable output
uv run python SimWorks/manage.py ai_healthcheck

# CI/CD JSON output
uv run python SimWorks/manage.py ai_healthcheck --json
```

**JSON output schema:**

```json
{
  "ok": true,
  "http_status": 200,
  "detail": "..."
}
```

On crash:
```json
{
  "ok": false,
  "http_status": 500,
  "detail": "",
  "error": "..."
}
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Healthy |
| `1` | Healthcheck failed (`ok: false`, `http_status: 503`) |
| `2` | Healthcheck crashed unexpectedly (`http_status: 500`) |

### Side effects

- Attempts to call `app.start()` before running the healthcheck (failure is non-fatal and only logged at DEBUG).
- No database writes.

### Notes / caveats

- Requires a configured OrchestrAI app (`ORCA_ENTRYPOINT` or equivalent app setup).
- Use `--json` for structured output in CI scripts so you can parse `http_status` and `ok` reliably.
- Safe to call repeatedly; no destructive side effects.

---

## `run_service`

### Purpose

Executes a registered OrchestrAI service from the command line. Useful for one-off service invocations, local debugging, and dry-run validation of service wiring.

### Usage

```
uv run python SimWorks/manage.py run_service <service> [options]
```

### Options

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `service` | `str` (positional) | — | **Yes** | Service registry identity (e.g. `services.chatlab.standardized_patient.initial`) |
| `-c` / `--context` | JSON `str` | `{}` | No | Base JSON context dict passed to the service |
| `--context-json` | JSON `str` | — | No | JSON string merged into context (overrides `--context` on key collision) |
| `--context-file` | `str` (path) | — | No | Path to a JSON file merged into context (highest precedence) |
| `--mode` | `start` \| `schedule` \| `astart` \| `aschedule` | `start` | No | Execution method; `astart`/`aschedule` use `asyncio.run()` |
| `--log-level` | `DEBUG`\|`INFO`\|`WARNING`\|`ERROR`\|`CRITICAL` | `INFO` | No | Logging verbosity |
| `--dry-run` | flag | `False` | No | Instantiate service with `dry_run=True`; skips outbound client calls |

### Context merge order

Context from the three sources is merged left-to-right; later sources override earlier ones:

```
--context  →  --context-json  →  --context-file
```

### Examples

```bash
# Run a service with no context
uv run python SimWorks/manage.py run_service services.chatlab.standardized_patient.initial

# Pass simulation context
uv run python SimWorks/manage.py run_service services.chatlab.standardized_patient.initial \
  --context '{"simulation_id": 42}'

# Dry run with extra debug logging
uv run python SimWorks/manage.py run_service services.chatlab.standardized_patient.initial \
  --context '{"simulation_id": 42}' --dry-run --log-level DEBUG

# Use a context file
uv run python SimWorks/manage.py run_service services.chatlab.stitch.pulse \
  --context-file /tmp/sim_context.json --mode astart
```

### Side effects

- Executes the service, which **may write to the database**, call external AI providers, or trigger outbox events — unless `--dry-run` is set.
- `--dry-run` skips outbound client calls but may still execute local setup/teardown logic inside the service.
- Output (if any) is printed as JSON or `repr()` to stdout.

### Notes / caveats

- Requires a configured OrchestrAI app; fails with `CommandError` if no app is active (`ORCA_ENTRYPOINT` must be set and auto-started).
- The service identity must be registered in the OrchestrAI registry (discovery must have run). An unregistered identity raises a `CommandError`.
- `--mode schedule` / `--mode aschedule` enqueues the service rather than running it inline — ensure a task worker is running to process it.
- Treat as a **developer/ops tool**; do not use in automated pipelines where side effects must be controlled. Prefer `--dry-run` for validation.
