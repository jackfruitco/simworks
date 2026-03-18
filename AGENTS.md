# AGENTS.md

## Purpose

Root control-tower instructions for coding agents working in this repository.

## How to apply guidance

1. Follow direct task/user instructions first.
2. Read this file and `docs/agents/README.md`.
3. Apply nearest scoped `AGENTS.md` files for touched paths.
4. Prefer one source of truth; avoid duplicating rules across docs.

## Repo-wide always-on rules

- Use MedSim as product branding in human-facing docs; preserve legacy `simworks`/`SimWorks` technical identifiers unless explicitly requested.
- Use `uv` workflows (`uv sync`, `uv run ...`) for Python/Django/package tasks.
- Keep root `AGENTS.md` and `CLAUDE.md` short; detailed guidance belongs in `docs/agents/`.
- Update links/indexes when moving or restructuring docs.

## Never-violate rules

- Do not break architecture boundaries (`orchestrai` must stay framework-agnostic; no import path from core to `orchestrai_django`).
- Do not introduce GraphQL or SPA frameworks unless explicitly requested by new architecture decisions.
- Do not treat WebSockets as source of truth; preserve API catch-up and outbox durability patterns.

## Detailed guidance map

- Shared docs index: `docs/agents/README.md`
- Repo standards: `docs/agents/repo-standards.md`
- Testing and quality: `docs/agents/testing-and-quality.md`
- Architecture boundaries: `docs/agents/architecture-and-boundaries.md`
- AI/prompt guidance: `docs/agents/ai-and-prompting.md`
- Simulation domain rules: `docs/agents/domain-simulation-rules.md`
