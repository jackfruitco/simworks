# MedSim Backup and Restore

MedSim uses PostgreSQL logical backups for durable disaster recovery and account-critical restores. Backups are compressed with `zstd`, encrypted with `age`, and stored in a private Cloudflare R2 bucket.

## Modes

- `full`: backs up the whole PostgreSQL database, including simulation history. Use for disaster recovery.
- `core`: backs up only identity, account access, invitations, billing state, entitlements, and provider IDs needed to restore access without simulation history.

Core mode is a data-only dump intended to load into a freshly migrated schema. It intentionally excludes sessions, account/invitation audit events, billing webhook events, simulation data, chat data, TrainerLab runtime data, outbox rows, service-call logs, feedback, assessment history, temporary rows, and generated history. A future `core_audit` mode may include audit and webhook event tables, but it is not implemented.

## Core Tables

Core backups include:

- `django_content_type`, `auth_permission`, `auth_group`, `auth_group_permissions`, `django_site`
- `accounts_user`, `accounts_user_groups`, `accounts_user_user_permissions`
- `accounts_userrole`, `accounts_roleresource`
- `account_emailaddress`, `account_emailconfirmation`
- `socialaccount_socialapp`, `socialaccount_socialaccount`, `socialaccount_socialtoken`
- `accounts_account`, `accounts_accountmembership`, `accounts_lab`, `accounts_labmembership`, `accounts_invitation`
- `billing_billingaccount`, `billing_subscription`, `billing_entitlement`, `billing_seatallocation`, `billing_seatassignment`

## Environment

Backup sidecar environment:

```env
BACKUP_ENVIRONMENT=production
BACKUP_R2_BUCKET=medsim-backups
BACKUP_R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
BACKUP_R2_ACCESS_KEY_ID=...
BACKUP_R2_SECRET_ACCESS_KEY=...
BACKUP_AGE_PUBLIC_KEY=age1...
```

Manual restore environment:

```env
BACKUP_R2_BUCKET=medsim-backups
BACKUP_R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
BACKUP_R2_ACCESS_KEY_ID=...
BACKUP_R2_SECRET_ACCESS_KEY=...
BACKUP_AGE_PRIVATE_KEY=AGE-SECRET-KEY-...
```

Use separate R2 credentials. The backup sidecar should have write access for backup objects and latest pointers. Restore credentials should be read-only and should not be present in the always-running app or backup sidecar. If the R2 account supports Object Lock or retention rules for the bucket, enable them for backup prefixes; otherwise use IAM-scoped credentials and avoid broad admin tokens.

## Object Layout

Backups use this key structure:

```text
<environment>/<mode>/YYYY/MM/DD/<mode>-YYYYMMDDTHHMMSSZ.dump.zst.age
<environment>/<mode>/YYYY/MM/DD/<mode>-YYYYMMDDTHHMMSSZ.manifest.json
<environment>/<mode>/latest.json
```

The manifest records the mode, environment, Django settings module, database name, migration heads, table list, encryption/compression settings, encrypted artifact SHA-256, size, and object keys. Upload verification requires the object size to match and, for backup artifacts, requires R2 checksum metadata to contain the expected SHA-256 value.

## Manual Backup

Preview a core backup without running tools or uploading:

```bash
uv run python manage.py backup_database --mode core --dry-run
```

Create and verify a core backup:

```bash
uv run python manage.py backup_database \
  --mode core \
  --upload r2 \
  --encrypt \
  --verify-upload
```

The command requires PostgreSQL and passes the database password only through `PGPASSWORD`. A shared PostgreSQL advisory lock prevents core and full backups from overlapping.

## Sidecar Cron

`docker/compose.yaml` includes a `backup` service that runs cron inside Docker. Defaults:

```cron
0 3 * * * core backup
0 4 * * * full backup
```

Use `BACKUP_CRON_ENABLE_CORE=false` or `BACKUP_CRON_ENABLE_FULL=false` to disable a scheduled mode. Cron jobs explicitly source the generated backup environment file and redirect command output to the container stdout/stderr streams, so backup logs appear in normal container logs.

## Restore Procedure

Core restore is designed for a clean database lifecycle:

```bash
# 1. Create/recreate containers and database volume.
# 2. Run migrations first.
uv run python manage.py migrate

# 3. Dry-run restore validation. This resolves latest.json, downloads the encrypted
# object, and verifies checksum without writing to the database.
uv run python manage.py restore_database \
  --mode core \
  --backup-key production/core/latest.json \
  --dry-run

# 4. Restore core data.
uv run python manage.py restore_database \
  --mode core \
  --backup-key production/core/latest.json \
  --require-empty-db

# 5. Validate relationships explicitly.
uv run python manage.py check_core_restore

# 6. Seed only missing defaults if needed.
uv run python manage.py seed_roles
```

The restore command checks for non-seed business data before writing. A freshly migrated database may contain default roles and system users; those are allowed. The command then truncates the core allowlist tables in deterministic FK-safe order, runs `pg_restore`, reseeds restored serial/identity sequences so future inserts do not collide with restored primary keys, expires pending invitations inside a transaction, and runs post-restore validation.

Core restore migration compatibility checks are limited to account, auth, allauth, site, content type, and billing apps represented in the core table allowlist. Unrelated simulation or TrainerLab migration changes do not block a core restore because those tables are intentionally excluded.

To intentionally overwrite an already populated database, pass `--truncate-managed-tables`. This is destructive and should not be used for normal production restore.

Full restores require `--require-empty-db` and a fresh migrated database. The command refuses to run a full restore if public application tables contain rows. Use a newly created database and run migrations before invoking a full restore.

## Invitation Policy

Invitations are backed up, but pending invitations contain sensitive tokens. After restore, pending unclaimed invitations are expired in a transaction by default. Use `--preserve-pending-invitations` only when restoring into a controlled environment where old pending invite links should remain valid.

## Key Rotation

Generate a new age key pair, update the sidecar with the new public key, and keep both old and new private keys available until all backups encrypted with the old key expire. Do not store private keys in R2 or in always-running containers.

The scheduled backup sidecar only needs `BACKUP_AGE_PUBLIC_KEY`. Keep `BACKUP_AGE_PRIVATE_KEY` out of the sidecar and provide it only in a manual restore environment.
