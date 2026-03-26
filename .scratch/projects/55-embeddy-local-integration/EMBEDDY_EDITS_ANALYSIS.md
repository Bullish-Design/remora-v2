# EMBEDDY Edits Analysis

## 1. Executive Summary

The proposed change set is directionally correct and mostly necessary.

Core conclusion:
- `embeddy` has true upstream blockers for local mode (model load/encode path is not implemented and startup does not preload model).
- `remora-v2` also needs independent hardening, even after upstream embeddy fixes, to provide stable API/CLI behavior under real backend faults.

Recommended ownership split:
- Implement backend/model-readiness behavior in `embeddy`.
- Implement error semantics, index strictness, and defensive handling in `remora-v2`.

## 2. What Was Investigated (remora-v2 + embeddy reference)

remora-v2:
- `src/remora/core/services/search.py`
- `src/remora/web/routes/search.py`
- `src/remora/__main__.py` (`_index`)
- `tests/unit/test_search.py`
- `tests/unit/test_web_server.py` (search route coverage)
- `tests/integration/test_search_remote_backend.py`
- `docs/HOW_TO_USE_REMORA.md`
- `remora.yaml.example`

embeddy reference used for root-cause validation:
- `.context/embeddy/src/embeddy/embedding/backend.py`
- `.context/embeddy/src/embeddy/cli/main.py`
- `.context/embeddy/src/embeddy/config.py`
- `.context/embeddy/src/embeddy/server/routes/health.py`

## 3. Verified Findings

### F1: embeddy local backend is not implemented (hard blocker)

Evidence:
- `.context/embeddy/src/embeddy/embedding/backend.py:132-152` has `NotImplementedError` for local `_load_model_sync` and `_encode_sync`.
- `.context/embeddy/src/embeddy/embedding/backend.py:107-109` raises `ModelLoadError("Model not loaded — call load() first")` if encode is called before load.

Impact on remora:
- remora local mode can initialize and mark available, but first real semantic operation can fail at runtime.

Verdict:
- Required upstream embeddy fix.

### F2: embeddy server startup does not load local model

Evidence:
- `.context/embeddy/src/embeddy/cli/main.py:80-107` builds `Embedder` and `VectorStore`, but does not call any model load hook before serving.
- No explicit readiness check is wired before `uvicorn.run`.

Impact on remora:
- Health may pass while first embed/search request fails.

Verdict:
- Required upstream embeddy fix.

### F3: embeddy env-only config path is inconsistent

Evidence:
- `.context/embeddy/src/embeddy/cli/main.py:49-60` defaults to `EmbeddyConfig()` when no config file is passed.
- `.context/embeddy/src/embeddy/config.py:208-291` has `EmbedderConfig.from_env`, but it is not used by `_resolve_config`.

Impact on remora:
- Local/remote mode may not follow environment-only setups unless config file is supplied.

Verdict:
- Required upstream embeddy fix.

### F4: remora local initialization marks service available without load handshake

Evidence:
- `src/remora/core/services/search.py:120-132` creates local embedder/pipeline and immediately sets `_available = True`.
- No explicit embedder load/readiness check exists in remora local init.

Impact:
- False-positive availability in local mode under partially ready backends.

Verdict:
- Required remora hardening.

### F5: remora remote initialize catches too narrow an exception set

Evidence:
- `src/remora/core/services/search.py:73-83` catches only `(OSError, TimeoutError)` around `await self._client.health()`.
- embeddy client can raise domain exceptions (for non-200 responses), not guaranteed to be caught here.

Impact:
- Startup can raise unexpectedly instead of degrading search availability.

Verdict:
- Required remora hardening.

### F6: `/api/search` lacks structured backend exception mapping

Evidence:
- `src/remora/web/routes/search.py:62-64` directly awaits `deps.search_service.search(...)` with no `try/except`.
- Existing tests only cover configured/unavailable/validation/happy path, not backend exceptions (`tests/unit/test_web_server.py:665-797`).

Impact:
- Backend faults can become unstructured 500 responses.

Verdict:
- Required remora hardening.

### F7: `remora index` soft-fails on per-file indexing errors

Evidence:
- `src/remora/__main__.py:256-284` accumulates `errors` and always prints summary.
- No non-zero exit on indexing errors.

Impact:
- CI/demo strict checks can pass command execution while indexing materially failed.

Verdict:
- Required remora hardening for strict workflows.

### F8: local mode collection behavior is inconsistent

Evidence:
- `src/remora/core/services/search.py:216-223`, `228-234`, `246-257`.
- Local pipeline is built once with `collection=self._config.default_collection` (`124-129`), and local index/reindex/delete paths ignore computed `target`.

Impact:
- `collection_map` is effectively remote-only for indexing behavior.

Verdict:
- Required remora correctness fix (or explicit documented limitation if intentionally deferred).

### F9: docs/config do not provide complete local-mode operational guidance

Evidence:
- Search docs focus on remote server setup (`docs/HOW_TO_USE_REMORA.md:481-539`).
- `remora.yaml.example:63-75` shows remote-only commented sample.

Impact:
- Local-model setup is ambiguous and prone to misconfiguration.

Verdict:
- Recommended remora docs fix; strongly advised for “real world” adoption.

## 4. Verdict on Proposed Change Map

### Embeddy (upstream) proposals

1. Implement local backend loading and encoding:
- Status: Required.
- Notes: This is the primary blocker; remora should not own model implementation internals.

2. Ensure local model is loaded during server startup:
- Status: Required.
- Notes: Should fail fast on startup if local mode selected and model cannot load.

3. Fix config/env application for embedder mode:
- Status: Required.
- Notes: CLI/config resolution should consistently honor env vars without mandatory config file.

4. Strengthen readiness semantics:
- Status: Strongly recommended.
- Notes: Health/readiness should reflect “model loaded and usable”, not just process alive.

5. Embeddy test additions:
- Status: Required.
- Notes: Needed to prevent regressions in load/readiness semantics.

### remora-v2 proposals

1. Local search initialization robustness:
- Status: Required.
- Clean approach: keep remora defensive, but do not deeply depend on private embeddy internals.

2. API error handling for backend exceptions:
- Status: Required.
- Clean approach: structured `error_response` mapping with stable error keys.

3. CLI indexing failure semantics:
- Status: Required.
- Clean approach: strict mode switch (or strict-by-default with explicit `--allow-errors` escape hatch).

4. remora test updates:
- Status: Required.

5. docs/config guidance:
- Status: Required for operational clarity.

## 5. Additional Needed Remora Edits (not explicit in overview)

1. Local-mode collection consistency:
- Ensure local indexing/reindex/delete honors target collection semantics.

2. Route default collection source:
- `api_search` should not hardcode `"code"` when `SearchConfig.default_collection` differs.

3. Initialize-path exception normalization:
- Capture embeddy-domain failures into remora-level availability state with actionable logs.

## 6. Cleanest Implementation Strategy (Recommended)

## Phase A: Upstream Contract Alignment (embeddy first)

1. Define stable readiness contract:
- “ready” means model loaded and encode/search calls can succeed.

2. Implement local backend + startup preload + env config correctness.

3. Add embeddy tests for:
- local load/encode success/failure,
- startup fail-fast behavior,
- env-only mode resolution,
- readiness endpoint semantics.

Why first:
- Prevents remora from implementing brittle workarounds against unfinished backend behavior.

## Phase B: remora Defensive Hardening (independent, can start immediately)

1. `SearchService.initialize`:
- Broaden handling of backend health exceptions.
- On failure: set unavailable, capture reason in logs, do not crash runtime startup.

2. `/api/search`:
- Add structured exception mapping around `search_service.search(...)`.
- Suggested map:
  - backend unavailable/readiness faults -> `503 search_backend_unavailable`
  - backend protocol/data faults -> `502 search_backend_error`
  - unexpected internal -> `500 internal_error`

3. `remora index`:
- Add strictness behavior:
  - `--fail-on-errors/--allow-errors` (recommended shape).
  - exit non-zero when strict and aggregated `errors` is non-empty.
- Improve diagnostics:
  - unavailable backend
  - backend reachable but not ready
  - per-file ingestion errors

## Phase C: remora Local-Mode Correctness

1. Honor collection target for local operations:
- Either instantiate per-collection local pipelines or provide explicit collection-aware ingest APIs.

2. Remove route hardcoded default `"code"`:
- Let service/config decide default when request omits `collection`.

## Phase D: Test + Docs Completion

1. Unit tests:
- local init model-load failure behavior.
- remote health non-`OSError` failure handling.
- `/api/search` structured error on backend exception.
- index strict-mode exit semantics.
- local collection-map behavior (if implemented).

2. Integration tests:
- keep remote real backend tests (`tests/integration/test_search_remote_backend.py`).
- add local backend integration module gated on local model env.

3. Docs:
- add explicit local mode setup path, runtime requirements, readiness checks, and troubleshooting.

## 7. Real-World Validation Matrix

After implementation, validate in this order:

1. Unit:
- `devenv shell -- pytest tests/unit/test_search.py tests/unit/test_web_server.py tests/unit/test_cli.py -q`

2. Integration (remote backend):
- `REMORA_TEST_SEARCH_URL=... devenv shell -- pytest tests/integration/test_search_remote_backend.py -q -rs`

3. Integration (local backend, real model):
- env-gated new module validating local init + search/index paths.

4. Runtime/API smoke:
- `devenv shell -- remora start`
- `curl -sS -X POST http://127.0.0.1:8080/api/search ...`
- assert structured error shape under induced backend failure.

5. Strict indexing:
- run `remora index` with strict mode and assert non-zero on induced ingest error.

## 8. Best/Cleanest/Elegant Principles for This Work

1. Keep ownership boundaries clean:
- embeddy owns model lifecycle/readiness internals.
- remora owns resilience, API contract, and operator UX.

2. Avoid private API coupling in remora:
- do not permanently rely on `embedder._backend` internals.

3. Fail clearly, not silently:
- availability should be truthful,
- API/CLI should return structured actionable diagnostics.

4. Add behavior tests for each fault class:
- unreachable backend,
- backend ready=false,
- backend runtime exception,
- partial ingest errors.

## 9. Final Recommendation

Yes, the proposed edits are necessary overall.

Priority order:
1. embeddy upstream local-mode/readiness/env fixes,
2. remora structured error handling + strict index semantics,
3. remora local collection consistency + doc updates,
4. comprehensive real-backend tests.

This sequence yields the cleanest long-term architecture with minimal coupling and robust real-world behavior.
