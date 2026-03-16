# Decisions — Companion Integration

## D1: Keep `TurnDigestedEvent.summary` despite Pydantic warning
The implementation guide uses `summary` on `TurnDigestedEvent`. This shadows `Event.summary()` and triggers a warning, but the serialized payload and tests are correct. Keep the field name to match the guide and expected event shape.

## D2: Use `correlation_id` instead of `timestamp` in Grail companion tools
Monty/Grail validation rejects importing `time` in `.pym` scripts. For KV companion entries, store `correlation_id` via `my_correlation_id()` instead of a wall-clock timestamp to keep tools valid and traceable.
