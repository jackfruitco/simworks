# Agent guidance library

This directory contains shared, tool-agnostic operating guidance for coding agents.

## How to use

1. Start with root `AGENTS.md` (or `CLAUDE.md` for Claude entry).
2. Read the relevant shared docs below.
3. Apply nearest scoped `AGENTS.md` rules for files you touch.
4. Follow direct task/user instructions if they conflict with generic guidance.

## Documents

- `repo-standards.md` — repo-wide engineering standards.
- `testing-and-quality.md` — required validation workflows.
- `architecture-and-boundaries.md` — architectural dependency boundaries.
- `ai-and-prompting.md` — orchestration/prompt/schema guidance.
- `domain-simulation-rules.md` — MedSim simulation and realtime constraints.

Keep these files concise and non-overlapping; avoid duplicating the same rule across multiple files.
