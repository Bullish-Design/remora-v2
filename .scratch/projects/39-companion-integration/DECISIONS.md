# Decisions — Companion Integration

## D1: Keep `TurnDigestedEvent.summary` despite Pydantic warning
The implementation guide uses `summary` on `TurnDigestedEvent`. This shadows `Event.summary()` and triggers a warning, but the serialized payload and tests are correct. Keep the field name to match the guide and expected event shape.
