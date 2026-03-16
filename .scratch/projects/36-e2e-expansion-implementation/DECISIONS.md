# Decisions

- Use a single acceptance module with shared runtime helpers for consistency and lower maintenance.
- Start runtime via `_start(...)` with live web socket, not ASGI transport, to cover process-boundary web behavior.
