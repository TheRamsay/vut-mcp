# AGENTS.md

Minimal guidance for agents working in this repository.

## Project Shape

- Python 3.12 project managed with `uv`.
- `src/vut_studis/` contains the Studis client, auth, parsers, and domain models.
- `src/vut_mcp/` should stay a thin MCP layer over `vut_studis`.
- `tests/` contains parser and behavior tests; fixtures must stay anonymized.

## Commands

- Install dev environment: `uv sync --extra dev`
- Run tests: `uv run pytest`
- Run lint: `uv run ruff check .`
- Start MCP server: `uv run vut-mcp`
- Run debug CLI: `uv run vut-studis-debug <command>`

## Working Rules

- Keep the MVP read-only unless the user explicitly asks otherwise.
- Do not commit secrets, real Studis data, cookies, or raw personal fixtures.
- Prefer typed models and focused parsers over ad hoc dictionaries.
- Keep `vut_mcp` orchestration-only; put Studis-specific logic in `vut_studis`.
- Add or update focused tests for parser/client behavior changes.
- Preserve existing user changes in the worktree; do not revert unrelated edits.
- Keep agent-only planning artifacts under `docs/superpowers/` local; never stage or commit them.
