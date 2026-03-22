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

Remediation pass completed:
- Updated `README.md` for correct config key names, current CLI command set, node-type wording, and `devenv shell --` test commands.
- Updated `docs/user-guide.md` (`query_search_paths`, `bundle_search_paths`, env guidance, snake_case event examples).
- Updated `docs/architecture.md` with correct module paths, node schema field (`text`), reconciler `ContentChangedEvent` subscription behavior, and extension guidance.
- Updated `docs/externals-contract.md` compatibility rule to hard-fail semantics.
- Updated `docs/externals-api.md` with tag-aware event signatures, snake_case event-type examples, and search capability section.
- Updated `remora.yaml.example` to remove invalid `file` overlay and use snake_case event type strings.
