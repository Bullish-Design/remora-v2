# Plan: Companion & Vector Integration for Remora v2

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do all work directly.**

## Goal

Design how to integrate two capabilities from v1 into v2's architecture:
1. **Companion system** — post-turn processing (summarize, categorize, link, reflect), sidebar composition, persistent agent memory
2. **Embeddy integration** — semantic vector search for agents via hybrid search

Both must align with v2's ethos: simple, clean, elegant. No backwards compatibility concerns.

## Deliverables

1. `COMPANION_BRAINSTORMING.md` — Full analysis and design for companion functionality
2. `VECTOR_BRAINSTORMING.md` — Full analysis and design for embeddy integration

## Steps

1. Study v1 companion system in full (NodeAgent, MicroSwarms, sidebar, indexing) — DONE
2. Study embeddy codebase and API in full — DONE
3. Study v2 core architecture for integration points — DONE
4. Write COMPANION_BRAINSTORMING.md (TOC-first, then sections)
5. Write VECTOR_BRAINSTORMING.md (TOC-first, then sections)
6. Create CONTEXT.md and PROGRESS.md

**REMINDER: NO SUBAGENTS.**
