# Decisions

- Decision: separate recommendations into `embeddy-upstream-required` vs `remora-required`.
  - Rationale: avoids coupling remora to embeddy internals and keeps ownership boundaries clear.
- Decision: recommend defensive error handling in remora even if embeddy is fixed upstream.
  - Rationale: backend faults will still occur in production and should never produce unstructured API failures.
- Decision: include additional remora-local findings not explicitly listed in the overview (collection-map/local mode behavior, hardcoded API default collection, narrow remote health exception handling).
  - Rationale: these are real correctness/operability gaps discovered during code audit.
