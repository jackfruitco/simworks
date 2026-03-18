# Documentation system audit (2026-03)

## Current problems identified

1. **Root instruction files were unbalanced**
   - `CLAUDE.md` had grown into a very large monolithic file with mixed concerns (architecture, commands, conventions, AI specifics, app specifics).
   - There was **no root `AGENTS.md`**, so instruction hierarchy started only at subdirectories.

2. **Guidance scope was blurred**
   - Repo-wide rules, Django-app-specific rules, and package-specific rules were mixed together.
   - Some instructions were agent-only but lived alongside human onboarding guidance.

3. **Contradiction/staleness risks**
   - `SimWorks/AGENTS.md` referenced updating a specific section in `CLAUDE.md`, which is brittle when `CLAUDE.md` structure changes.
   - Large instruction docs increase drift risk and make conflict resolution difficult.

4. **Navigation gaps**
   - No dedicated map for the instruction system itself (what is authoritative, where to look first, how local overrides work).

## Target structure

- Short control-tower roots:
  - `/AGENTS.md`
  - `/CLAUDE.md`
- Shared detailed agent guidance in:
  - `/docs/agents/README.md`
  - `/docs/agents/repo-standards.md`
  - `/docs/agents/testing-and-quality.md`
  - `/docs/agents/architecture-and-boundaries.md`
  - `/docs/agents/ai-and-prompting.md`
  - `/docs/agents/domain-simulation-rules.md`
- Existing scoped `AGENTS.md` files remain near subsystems but become concise and pointer-based.
- Add a documentation map for both humans and agents:
  - `/docs/meta/documentation_map.md`

## Files created/updated in this refactor

- Created root control files: `AGENTS.md`.
- Rewrote root `CLAUDE.md` to a concise control-tower format.
- Created shared agent docs library under `docs/agents/`.
- Added `docs/meta/documentation_map.md`.
- Updated scoped `AGENTS.md` files (`SimWorks/`, `packages/orchestrai/`, `packages/orchestrai_django/`) to align with hierarchy and reduce duplication.
- Updated docs indexes (`README.md`, `docs/index.md`, `docs/README.md`) to expose the new map and instruction entry points.

## Notable stale/contradictory guidance fixed

- Removed dependency on a specific `CLAUDE.md` section name as a required update target.
- Consolidated repeated architecture/testing rules into shared docs to avoid multiple diverging copies.
- Clarified authority split: root control files -> shared docs -> scoped `AGENTS.md` for local constraints.
