# REPO RULES — Remora

## ABSOLUTE RULES — READ FIRST

1. **NO SUBAGENTS** — NEVER use the Task tool. Do ALL work directly. No exceptions.
2. **NEVER STOP AFTER COMPACTION** — Read CONTEXT.md, check PROGRESS.md, resume immediately. Keep working until the project is FULLY DONE.

---

Repo-specific standards and conventions. Loaded after `CRITICAL_RULES.md`.
These are **in addition to** the universal coding standards in CRITICAL_RULES.

---

## devenv.sh Environment (MANDATORY for execution/testing)

Use `devenv shell --` for commands that execute project code or tooling (tests, scripts, linters, formatters, dependency sync, app/runtime commands).  
You do **not** need `devenv shell --` for routine read-only shell inspection commands (e.g. `ls`, `cat`, `rg`, `git log`, `git show`).

**CRITICAL: Before the first test run in every session, ALWAYS sync dependencies:**
```bash
devenv shell -- uv sync --extra dev
```

**NEVER use `uv pip install`. ALWAYS use `uv sync`.**

```bash
devenv shell -- pytest tests/unit/test_lsp_graph.py -v
devenv shell -- ruff check src/
devenv shell -- uv sync --extra dev
```
For scripts/tests/tooling, never run `python`, `pytest`, `uv run`, or similar directly from system PATH.

---

## Hard Dependencies

All packages in `pyproject.toml` `[project.dependencies]` are hard dependencies:
- Import unconditionally (no `try/except ImportError` guards).
- Test unconditionally (no `pytest.mark.skipif` for missing deps).

---

## Coding Standards (repo-specific)

- **No isinstance in business logic**: Projection dispatch (internal) is the exception.
- **AgentNode**: Single Pydantic BaseModel. No subclasses anywhere.

---

## Key Reference Files

| Document | Path |
|----------|------|
| Vision / architecture | `docs/EventBased_Concept.md` |
| Architecture alignment | `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md` |
| AgentNode design spec | `docs/plans/2026-03-02-agentnode-design.md` |
| AgentNode impl plan | `docs/plans/2026-03-02-agentnode-implementation.md` |

---

## Architecture Overview

Remora is a reactive agent swarm system where code nodes (functions, classes, methods, files) become autonomous AI agents communicating via events.

- **EventStore** is the single source of truth. Every state change is an event.
- **AgentNode** (Pydantic BaseModel) represents any code node. Specialization is data-driven via `AgentExtension`, not subclasses.
- **NodeProjection** materializes events into the `nodes` table as a read-optimized view.
- **RemoraDB** holds LSP-specific operational state only: edges, proposals, cursor_focus, command_queue, events, activation_chain.

---

## Test Suite

```
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

Known pre-existing failures:
- `test_lsp_handlers_register_and_advertise_capabilities` — missing `workspace/executeCommand` in capabilities.
- 2 cairn merge-ops tests (skipped via `--ignore`).
- 1 benchmark timeout (skipped via `--ignore`).
