# EMBEDDY Refactoring Guide for remora-v2

## Table of Contents

1. Purpose and Success Criteria
   - Defines the exact end-state required for embeddy to be production-functional for remora-v2.
2. Scope and Ownership Boundaries
   - Separates embeddy-upstream work from remora-v2 integration hardening.
3. Current Failure Modes (Verified)
   - Lists concrete runtime failures and where they originate.
4. Phase 1: Embeddy Core Refactor (Required)
   - Step-by-step implementation for local backend load/encode/readiness/config behavior.
5. Phase 2: Embeddy Test Suite Additions (Required)
   - Adds regression-proof tests for local mode, startup fail-fast, and env config paths.
6. Phase 3: remora-v2 Integration Hardening (Required)
   - Search service, API route, and CLI indexing behavior hardening.
7. Phase 4: remora-v2 Tests and Docs (Required)
   - Unit/integration coverage and operational documentation updates.
8. End-to-End Validation Matrix
   - Exact run order and pass criteria for real-world verification.
9. Rollout and Backward Compatibility Strategy
   - Safe deployment and change-management order.
10. Definition of Done
   - Final acceptance checklist.

## 1. Purpose and Success Criteria

This guide defines the required refactor plan to make embeddy fully operational for remora-v2 in real-world usage, including local-model mode and robust failure behavior.

Success criteria:
- Embeddy local mode can load a configured model and successfully serve embed/search requests.
- Embeddy startup fails fast if local mode is configured but model load fails.
- Embeddy config resolution works reliably from config file and/or environment variables.
- Remora search initialization and routes handle embeddy failures with stable, structured API responses.
- `remora index` can enforce strict failure semantics for CI/demo correctness.
- Tests cover all critical success and failure paths.

## 2. Scope and Ownership Boundaries

### Embeddy upstream scope (must be implemented in embeddy)
- Local backend implementation (model load + encode path).
- Startup preloading and readiness semantics for local mode.
- Config resolution behavior for env-only deployments.
- Embeddy-side regression tests for these behaviors.

### remora-v2 scope (must be implemented in remora-v2)
- Defensive integration hardening around embeddy failures.
- Structured API error mapping for search route.
- Strict indexing failure mode for CLI.
- Real-world coverage tests and docs updates.

### Non-goals
- Rewriting remora architecture around search provider abstractions.
- Implementing multimodal local embedding parity in first pass (text-first is acceptable for stabilization).

## 3. Current Failure Modes (Verified)

1. Local backend implementation gap in embeddy:
- `LocalBackend._load_model_sync()` and `_encode_sync()` are not implemented.
- Any local encode call can fail with `Model not loaded — call load() first`.

2. Embeddy server startup readiness gap:
- Embedder/store objects are built for `serve`, but local model is not preloaded before the service starts accepting requests.

3. Config/env resolution mismatch in embeddy CLI:
- Env-derived embedder fields exist (`EmbedderConfig.from_env`) but are not applied by default `_resolve_config` path when no config file is passed.

4. remora-v2 optimistic local availability:
- remora local search init marks service available without explicit model readiness handshake.

5. remora-v2 backend exception leakage:
- `/api/search` does not map backend exceptions into structured JSON errors.

6. remora-v2 index soft-fail behavior:
- `remora index` reports per-file errors but does not fail command by default for strict workflows.

7. Local collection behavior mismatch:
- remora local pipeline currently does not consistently honor target collections used for file indexing/reindex/deletion.

## 4. Phase 1: Embeddy Core Refactor (Required)

Implement this phase in embeddy first.

## Step 1.1: Implement local model load path

File:
- `embeddy/src/embeddy/embedding/backend.py`

Required updates:
- Implement `LocalBackend._load_model_sync()`.
- Ensure successful load sets a usable internal model handle (`self._model`).
- Use `EmbedderConfig` fields consistently:
  - `model_name`
  - `device`
  - `torch_dtype`
  - `attn_implementation`
  - `trust_remote_code`
  - `cache_dir`

Design rules:
- Raise `ModelLoadError` for expected load failures.
- Keep heavyweight imports inside method body when practical to reduce import-time failure radius.
- Log model/device/dtype details at info level once load succeeds.

Implementation notes:
- First pass can be text-only if multimodal path is not ready.
- If the model requires tokenizer + model objects, store both in `_model` (for example, a small struct/dict/tuple) and document expected shape in code comments.

## Step 1.2: Implement local encode path

File:
- `embeddy/src/embeddy/embedding/backend.py`

Required updates:
- Implement `LocalBackend._encode_sync(inputs, instruction)`.
- Support text embeddings for each `EmbedInput` item at minimum.
- Return `list[list[float]]` exactly matching backend contract.

Design rules:
- Validate that inputs are non-empty and text is present where required.
- Convert unexpected model inference failures to `EncodingError` via existing wrapper behavior.
- Keep output dimensionality coherent with configured model dimension semantics.

## Step 1.3: Load local model before serving requests

File:
- `embeddy/src/embeddy/cli/main.py`

Required updates:
- During dependency build or serve startup, explicitly call backend load for local mode before launching Uvicorn.

Recommended shape:
- In `_build_deps` (or immediately after), do:
  - if `config.embedder.mode == "local"`: `asyncio.run(embedder._backend.load())` (or public equivalent once exposed)
- If load fails:
  - print clear startup error,
  - exit non-zero,
  - do not start HTTP server.

Important:
- Do not silently degrade to running-but-unready behavior in local mode.

## Step 1.4: Fix config/env resolution in CLI startup

Files:
- `embeddy/src/embeddy/config.py`
- `embeddy/src/embeddy/cli/main.py`

Required updates:
- `_resolve_config` must consistently merge:
  1. defaults,
  2. file values (if provided),
  3. env overrides,
  4. CLI flag overrides.
- Ensure env-only deployments can set local/remote mode without mandatory config file.

Recommended clean implementation:
- Add `EmbeddyConfig.from_env()` (top-level), which internally uses `EmbedderConfig.from_env()` and optional env parsing for store/server if desired.
- `_resolve_config` should call the same merge helper regardless of whether `--config` was supplied.

## Step 1.5: Add truthful readiness semantics

Files:
- `embeddy/src/embeddy/server/routes/health.py`
- optionally `embeddy/src/embeddy/server/schemas.py`

Required updates:
- Health/readiness response must include model readiness state for local mode.
- Separate liveness from readiness if possible.

Recommended API:
- Keep `/api/v1/health` but enrich payload:
  - `status`: `ok|degraded`
  - `ready`: `true|false`
  - `mode`: `local|remote`
  - optional `reason` when not ready.

Behavior:
- Local mode: `ready` should be true only after successful model load.
- Remote mode: `ready` should reflect remote backend health check.

## Step 1.6: Preserve exception contract and observability

Files:
- `embeddy/src/embeddy/embedding/backend.py`
- `embeddy/src/embeddy/server/app.py` (if mapping adjustments needed)

Required updates:
- Keep predictable exception types (`ModelLoadError`, `EncodingError`) for caller handling.
- Ensure server error responses remain structured JSON with stable error keys.
- Add logs that distinguish:
  - model load failure,
  - encode runtime failure,
  - readiness false state.

## 5. Phase 2: Embeddy Test Suite Additions (Required)

If embeddy lacks comprehensive tests today, add a focused module set first. Use unit tests with monkeypatching for model internals and one integration-style startup test.

## Step 2.1: Local backend load tests

Suggested file:
- `embeddy/tests/unit/test_embedding_local_backend.py`

Add tests:
1. `test_local_backend_load_success_sets_model`
2. `test_local_backend_load_failure_raises_model_load_error`
3. `test_local_backend_encode_without_load_raises_model_load_error`

## Step 2.2: Local encode tests

Same module or split module.

Add tests:
1. `test_local_backend_encode_returns_vectors_for_text_inputs`
2. `test_local_backend_encode_handles_instruction`
3. `test_local_backend_encode_failure_surfaces_encoding_error`

## Step 2.3: CLI startup fail-fast tests

Suggested file:
- `embeddy/tests/unit/test_cli_serve_startup.py`

Add tests:
1. local mode load success -> serve path continues.
2. local mode load failure -> command exits non-zero before Uvicorn starts.
3. remote mode -> no local load call required.

## Step 2.4: Config merge/env tests

Suggested file:
- `embeddy/tests/unit/test_config_resolution.py`

Add tests:
1. env-only `EMBEDDY_EMBEDDER_MODE=remote` reflected in resolved config.
2. file + env conflict precedence is deterministic and documented.
3. CLI flags override both env and file values.

## Step 2.5: Readiness endpoint tests

Suggested file:
- `embeddy/tests/integration/test_health_readiness.py`

Add tests:
1. local mode ready=true after successful preload.
2. local mode startup failure path never exposes ready service.
3. remote mode readiness reflects remote health state.

## 6. Phase 3: remora-v2 Integration Hardening (Required)

Implement this phase in remora-v2 after embeddy core fixes are underway.

## Step 3.1: Harden remote initialize exception handling

File:
- `src/remora/core/services/search.py`

Required update:
- In remote mode `initialize()`, catch broader backend/client exceptions, not only `(OSError, TimeoutError)`.

Recommended behavior:
- On any health-check failure:
  - set `_available = False`,
  - log actionable message with URL and exception summary,
  - do not crash runtime startup.

## Step 3.2: Add local readiness handshake (defensive)

File:
- `src/remora/core/services/search.py`

Required update:
- In local mode init, verify backend is truly ready before setting `_available=True`.

Clean approach hierarchy:
1. Preferred: rely on stable embeddy public readiness API (if introduced).
2. Interim defensive fallback: perform a tiny embed operation or explicit backend health probe during initialization, catch failure, set unavailable.

Design rule:
- remora should not permanently couple to embeddy private internals (for example, `_backend`), except temporary guarded fallback if no public API exists.

## Step 3.3: Fix local collection behavior consistency

File:
- `src/remora/core/services/search.py`

Problem:
- Local pipeline operations currently ignore computed target collection semantics in index/reindex/delete paths.

Required update:
- Ensure local operations honor collection selection consistently with remote behavior.

Implementation options:
- Option A (clean): maintain per-collection local pipeline instances keyed by collection name.
- Option B (acceptable): add collection-aware pipeline APIs and pass target explicitly.

Recommendation:
- Option A is cleaner if embeddy pipeline remains collection-bound at construction time.

## Step 3.4: Structure `/api/search` backend error handling

File:
- `src/remora/web/routes/search.py`

Required update:
- Wrap `deps.search_service.search(...)` in `try/except` and map failures through `error_response`.

Suggested mapping:
- backend unavailable/readiness failure -> `503 search_backend_unavailable`
- backend protocol/data/contract failure -> `502 search_backend_error`
- unexpected internal failure -> `500 internal_error`

Also update:
- Avoid hardcoding default `collection = "code"` when config default differs. Prefer service/config default path.

## Step 3.5: Add strict indexing failure semantics

File:
- `src/remora/__main__.py`

Required update:
- Extend `index` command with strictness control.

Recommended CLI flags:
- `--fail-on-errors/--allow-errors` (default should favor strict behavior in CI-sensitive environments).

Required behavior:
- If aggregated indexing errors > 0 and fail-on-errors is active:
  - print summary,
  - exit with non-zero status.

Also improve diagnostics for:
- backend unavailable,
- backend reachable but not ready,
- per-file ingestion errors.

## 7. Phase 4: remora-v2 Tests and Docs (Required)

## Step 4.1: Expand unit coverage for search service init behavior

File:
- `tests/unit/test_search.py`

Add tests:
1. remote health raises non-network backend exception -> service degrades (`available=False`) rather than raising.
2. local init readiness failure -> service remains unavailable.
3. local collection selection behavior is respected for index/reindex/delete paths (post-fix behavior).

## Step 4.2: Add `/api/search` exception mapping tests

File:
- `tests/unit/test_web_server.py`

Add tests:
1. search service throws backend-ready exception -> `503 search_backend_unavailable`.
2. search service throws backend protocol exception -> `502 search_backend_error`.
3. unexpected search exception -> `500 internal_error`.
4. validate payload shape (`error`, `message`, optional `docs`).

## Step 4.3: Add CLI strict indexing tests

File:
- `tests/unit/test_cli.py`

Add tests:
1. aggregated index errors with `--fail-on-errors` -> exits non-zero.
2. aggregated index errors with `--allow-errors` -> exits zero, prints warnings.
3. unavailable backend still exits non-zero with actionable diagnostics.

## Step 4.4: Preserve and extend real-backend integration coverage

Files:
- existing: `tests/integration/test_search_remote_backend.py`
- new: `tests/integration/test_search_local_backend.py` (env-gated)

For new local module, gate by explicit env contract, for example:
- `REMORA_TEST_LOCAL_SEARCH=1`
- `REMORA_TEST_LOCAL_MODEL_NAME=...`

Required scenarios:
1. local search service initialize + readiness success.
2. local search query returns structured response.
3. local index/reindex/delete path executes without hidden collection mismatch.
4. `/api/search` route end-to-end in local mode.

## Step 4.5: Update docs and example config

Files:
- `docs/HOW_TO_USE_REMORA.md`
- `remora.yaml.example`

Required docs additions:
- Local mode setup block with explicit dependency command (`search-local` extra).
- CPU/GPU memory expectations and caveats.
- Readiness verification commands.
- Troubleshooting table entries for:
  - model not loaded,
  - backend unreachable,
  - backend not ready,
  - strict index non-zero exits.

Required config additions:
- Add commented local-mode `search:` example with:
  - `mode: "local"`
  - `db_path`
  - `model_name`
  - `embedding_dimension`

## 8. End-to-End Validation Matrix

Run in this order.

## Stage A: embeddy unit/integration

1. embeddy backend/config/cli tests:
- `pytest embeddy/tests/unit -q`

2. embeddy readiness/integration:
- `pytest embeddy/tests/integration/test_health_readiness.py -q`

## Stage B: remora unit and integration

1. remora search-focused unit tests:
- `devenv shell -- pytest tests/unit/test_search.py tests/unit/test_web_server.py tests/unit/test_cli.py -q`

2. remora remote real-backend tests:
- `REMORA_TEST_SEARCH_URL=http://127.0.0.1:18585 devenv shell -- pytest tests/integration/test_search_remote_backend.py -q -rs`

3. remora local real-backend tests (new):
- env-gated run command for `tests/integration/test_search_local_backend.py`.

## Stage C: runtime smoke tests

1. Start runtime with local search enabled.
2. `POST /api/search` with valid payload -> 200 + structured results.
3. Induce backend failure -> assert structured error (no unhandled trace/plain 500).
4. Run `remora index` under strict mode with induced per-file error -> non-zero exit.

## 9. Rollout and Backward Compatibility Strategy

1. Merge embeddy upstream first (or pin remora to embeddy commit that includes required fixes).
2. Then merge remora hardening changes.
3. Keep temporary compatibility guards in remora only while embeddy contract stabilizes.
4. After embeddy release is stable, remove temporary fallback logic and rely on public readiness APIs.

Release note requirements:
- Document health/readiness response changes in embeddy.
- Document `remora index` strictness behavior and any new flags/defaults.
- Document local-mode operational requirements.

## 10. Definition of Done

All items below must be true:

- Embeddy local mode can load and encode in-process using configured model.
- Embeddy serve path fails fast when local model cannot load.
- Embeddy env-only mode resolution works and is tested.
- Embeddy health/readiness reflects actual model readiness.
- remora search initialize never crashes startup on backend failures.
- remora `/api/search` always returns structured JSON errors on backend faults.
- remora local collection behavior is consistent and tested.
- remora `index` strict mode exits non-zero when indexing errors occur.
- New/updated tests pass in CI and in real-world backend runs.
- remora docs and example config include complete local-mode guidance.
