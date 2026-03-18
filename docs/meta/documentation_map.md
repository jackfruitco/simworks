# Documentation map

## Authority order

1. **Direct task/user instructions**
2. **Root control files**: `AGENTS.md`, `CLAUDE.md`
3. **Scoped `AGENTS.md` files** in subdirectories (for local overrides)
4. **Shared agent guidance** in `docs/agents/`
5. **Human-facing engineering/product docs** in `README.md`, `docs/`, and package READMEs

## Start points by audience

### New engineers
- Root overview: `README.md`
- Platform docs index: `docs/index.md`
- Architecture: `docs/architecture.md`
- Local setup: `docs/quick-start.md`

### Coding agents (all tools)
- Root instructions: `AGENTS.md`
- Shared operating docs: `docs/agents/README.md`
- Then read nearest scoped `AGENTS.md` for touched files.

### Claude-specific entry
- `CLAUDE.md` (tool entry and pointers only)
- Then same shared docs under `docs/agents/`.

## Shared agent docs guide

- `docs/agents/repo-standards.md` — repo-wide engineering rules and conventions.
- `docs/agents/testing-and-quality.md` — validation commands and quality checks.
- `docs/agents/architecture-and-boundaries.md` — layer boundaries and dependency direction.
- `docs/agents/ai-and-prompting.md` — AI orchestration/prompt/schema rules.
- `docs/agents/domain-simulation-rules.md` — simulation-domain and real-time behavior constraints.

## Scoped instruction files

- `SimWorks/AGENTS.md` — Django app scope rules.
- `packages/orchestrai/AGENTS.md` — core orchestration package scope rules.
- `packages/orchestrai_django/AGENTS.md` — Django integration package scope rules.

## Maintenance rule

When behavior or architecture changes, update **one authoritative shared file first**, then only update scoped docs where local constraints differ.
