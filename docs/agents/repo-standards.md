# Repo-wide engineering standards

## General

- MedSim is the product name; preserve legacy `simworks`/`SimWorks` technical identifiers unless a change is explicitly requested.
- Prefer small, scoped changes over broad refactors.
- Keep docs and code updates consistent; do not leave contradictory statements.

## Commands and workflow

- Use `uv` for Python commands (`uv run ...`, `uv sync`).
- Run commands from repo root unless a package workflow explicitly requires otherwise.

## Documentation discipline

- Root control files (`AGENTS.md`, `CLAUDE.md`) must stay short and pointer-based.
- Shared rules belong in `docs/agents/`; local constraints belong in scoped `AGENTS.md` files.
- Human docs remain human-first; do not inject unnecessary agent behavior details into product docs.

## Change hygiene

- Avoid import-time side effects.
- Keep naming and terminology consistent with existing architecture docs.
- When moving/renaming docs, update links in indexes and READMEs in the same change.
