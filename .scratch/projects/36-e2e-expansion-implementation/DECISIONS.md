# Decisions

- Used a unified acceptance test module with shared runtime/LSP helpers to keep process-boundary tests consistent.
- For reactive acceptance, switched to a deterministic no-arg tool (`emit_mode_token`) to reduce model/tool argument variability.
- For proposal acceptance, validated materialized path from API response rather than assuming source-path normalization semantics.
- Implemented marker-driven test profile separation so deterministic and env-dependent suites can be selected explicitly.
