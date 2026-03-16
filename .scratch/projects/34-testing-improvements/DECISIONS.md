# Decisions

## 2026-03-15 - Property-based tests use Hypothesis in unit scope
- Decision: Add Hypothesis as a dev dependency and place property tests under `tests/unit/test_subscription_registry.py`.
- Rationale: Keeps property checks fast and deterministic while validating matching invariants across diverse input data.

## 2026-03-15 - Reconciler load test isolates reconcile/storage behavior
- Decision: Monkeypatch `workspace_service.provision_bundle` to no-op during the 1000x10 load test.
- Rationale: Prevents file-descriptor exhaustion from opening thousands of workspaces and keeps the load test focused on reconcile throughput/memory.
- Note: Runtime threshold set to `< 90s` to absorb CI host variance while still enforcing bounded performance at this scale.

## 2026-03-15 - Explicit skip reasons for real-LLM tests
- Decision: Replace shared marker alias with explicit `@pytest.mark.skipif(..., reason=...)` annotation on each of the 5 real-LLM tests.
- Rationale: Satisfies the documented requirement for explicit per-test skip reason annotations.
