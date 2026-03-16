# Plan: Embeddy Integration Implementation Guide

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do all work directly.**

## Goal

Create a detailed `EMBEDDY_IMPLEMENTATION_PLAN.md` — a step-by-step guide that an intern can follow to fully implement the embeddy integration into remora-v2, based on the design in `.scratch/projects/31-companion-and-vector-integration/VECTOR_BRAINSTORMING.md`.

## Deliverables

1. `EMBEDDY_IMPLEMENTATION_PLAN.md` — The main deliverable. Comprehensive, ordered implementation guide covering:
   - Each file to create/modify with exact code
   - Test files with exact test code
   - Configuration changes
   - Dependency changes
   - Verification steps at each stage

## Steps

1. Study codebase integration points in detail (config, services, externals, reconciler, web server) — DONE
2. Study embeddy client API signatures for accuracy — DONE
3. Verify brainstorming doc API calls match actual embeddy client — DONE
4. Write EMBEDDY_IMPLEMENTATION_PLAN.md (TOC-first, then sections)
5. Create CONTEXT.md and PROGRESS.md

## Open Questions (for user clarification)

- Should we include the FTS5 baseline (Approach F) as part of this plan, or just the embeddy integration?
- Should the plan include local mode support, or remote-only for simplicity?
- Any preferences on test structure (e.g., separate test file per module, or consolidated)?
- Should the Grail tool (`semantic_search.pym`) be included, or just TurnContext methods?

**REMINDER: NO SUBAGENTS.**
