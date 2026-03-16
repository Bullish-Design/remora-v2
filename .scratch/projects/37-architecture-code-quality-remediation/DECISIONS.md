# Decisions

- `2026-03-16`: Implemented item `4.1` using composition inside `core/actor.py` first (not cross-file extraction yet) to minimize test churn while reducing `Actor` responsibilities immediately.
- `2026-03-16`: Preserved legacy private method names and state attributes via wrappers/properties to maintain existing test and monkeypatch compatibility while shifting logic ownership to extracted components.
