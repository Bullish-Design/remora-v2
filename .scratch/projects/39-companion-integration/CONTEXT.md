# Context — Companion Integration

## Current State
Implementation has started from `IMPLEMENTATION_GUIDE.md`.

Completed:
- Step 1: Added `TurnDigestedEvent` to the event system.
  - Updated `src/remora/core/events/types.py` with new event model and export.
  - Updated `src/remora/core/events/__init__.py` exports.
  - Extended `tests/unit/test_events.py` with default/full/envelope coverage and instantiation coverage.
  - Verification: `devenv shell -- pytest tests/unit/test_events.py -q` (11 passed).
- Step 2: Added tag-based turn classification in actor completion flow.
  - `AgentTurnExecutor.execute_turn()` now classifies completion as:
    - `("primary",)` for normal turns
    - `("reflection",)` when triggered by `AgentCompleteEvent` tagged `primary`
  - `_complete_agent_turn()` now accepts `turn_tags` and emits them on `AgentCompleteEvent`.
  - Added actor tests for primary/reflection tagging in `tests/unit/test_actor.py`.
  - Verification: `devenv shell -- pytest tests/unit/test_actor.py -q` (31 passed).
- Step 3: Enriched `AgentCompleteEvent` with `user_message`.
  - Added `user_message: str = ""` to `AgentCompleteEvent` in `src/remora/core/events/types.py`.
  - `AgentTurnExecutor.execute_turn()` now captures user prompt content and passes it to completion emission.
  - `_complete_agent_turn()` now accepts `user_message` and includes it in emitted `AgentCompleteEvent`.
  - Added event-model and actor emission tests for `user_message`.
  - Verification: `devenv shell -- pytest tests/unit/test_events.py tests/unit/test_actor.py -q` (46 passed).

## Notes
- Pydantic emits a warning for `TurnDigestedEvent.summary` because `Event` also has a `summary()` method; behavior is correct and tests pass.

## Next Step
- Step 4: Add `not_from_agents` filter support to `SubscriptionPattern`.
