# Assumptions — Companion Integration

## Audience
An intern implementing the companion system into remora-v2. Needs detailed, actionable guidance.

## Source Material
- `.scratch/projects/31-companion-and-vector-integration/COMPANION_BRAINSTORMING.md` — the brainstorming document evaluating approaches
- The recommended approach: inline post-turn hooks with single LLM call
- Approach A: event-driven virtual agent observer pattern

## Constraints
- Must integrate with existing v2 primitives (Actor, EventStore, TurnContext, Workspace KV, Bundles)
- Should not duplicate what Actor already provides
- Should be configurable per-bundle
- Must work with the existing event system
- Post-turn processing should not block the main agent turn pipeline
