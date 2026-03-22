# CONTEXT

Completed full architecture + documentation review for remora-v2.

Artifacts:
- `CODE_ARCHITECTURE_NOTES.md`: implementation understanding (runtime flow, storage, events, actors, tooling, APIs).
- `DOC_REVIEW.md`: prioritized documentation findings with source-backed references and recommended fixes.

Top critical drifts identified:
1. Wrong config keys in docs (`query_paths`, `bundle_root`) vs runtime keys (`query_search_paths`, `bundle_search_paths`).
2. Event type examples use class names instead of runtime snake_case event strings.
3. Externals compatibility docs claim soft warning but runtime hard-fails on version mismatch.
4. Architecture docs contain stale module paths and wrong schema field names.
5. Environment variable examples for nested config fields do not work as documented.
