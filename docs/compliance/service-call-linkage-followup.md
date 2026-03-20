# Follow-up: Stronger Referential Integrity for Service Calls

Current risk: `ServiceCall.related_object_id` is a string and not a foreign key, so deletion safety depends on explicit cleanup services.

## Recommended migration path
1. Add nullable FK `simulation` on `ServiceCall`.
2. Backfill from `related_object_id` where parseable.
3. Add indexed FK-based queries for cleanup/export.
4. Keep legacy `related_object_id` for compatibility until downstream consumers migrate.
5. Remove legacy field in a later major migration.
