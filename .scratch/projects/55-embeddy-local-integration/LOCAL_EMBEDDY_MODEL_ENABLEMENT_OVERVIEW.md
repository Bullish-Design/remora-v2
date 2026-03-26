# Local Embeddy Model Enablement Overview

## Goal
Enable **real local-model semantic search** (no mock adapter) so that:
- `embeddy` can run in `mode=local` and actually embed/query.
- `remora-v2` search/index flows behave correctly against that local backend.
- `remora-test` strict checks (`REQUIRE_SEARCH=1`) pass with a real local setup.

## Current State (Observed)
- `remora-v2` search integration is wired for both `remote` and `local` modes in:
  - `src/remora/core/services/search.py`
- In practice, local-mode execution currently fails in embeddy with:
  - `Model not loaded — call load() first`
- Root causes in embeddy package implementation (0.3.x line):
  - local backend methods are still stubs (`NotImplementedError`) in `embedding/backend.py`
  - CLI/server startup path does not reliably load local model before serving
  - config/env handling for embedder mode is inconsistent unless explicit config file is provided
- Resulting behavior in remora:
  - `/api/search` can throw uncaught backend exceptions (500 plain text)
  - `remora index` may complete with per-file errors instead of hard-failing early

## Change Map: Embeddy (Primary Upstream Work)

### 1) Implement local backend loading and encoding
**Where:**
- `src/embeddy/embedding/backend.py`

**Needed changes:**
- Implement `LocalBackend._load_model_sync()`
  - load tokenizer/model pipeline for configured `model_name`
  - honor `device`, `torch_dtype`, `attn_implementation`, `trust_remote_code`, `cache_dir`
  - set loaded model handle on success
- Implement `LocalBackend._encode_sync()`
  - support text inputs at minimum (multimodal optional for first pass)
  - return deterministic vector lists sized to configured dimension behavior
  - preserve existing exception mapping (`EncodingError`, `ModelLoadError`)

### 2) Ensure local model is loaded during server startup
**Where:**
- `src/embeddy/cli/main.py`

**Needed changes:**
- In dependency construction/startup (`_build_deps` and/or `serve`), call backend load before accepting requests.
- Startup should fail fast with a clear error if model load fails.

### 3) Fix config/env application for embedder mode
**Where:**
- `src/embeddy/config.py`
- `src/embeddy/cli/main.py` (`_resolve_config`)

**Needed changes:**
- Ensure `EMBEDDY_EMBEDDER_MODE`, `EMBEDDY_REMOTE_URL`, etc. apply without requiring `--config` file.
- Keep explicit config file precedence rules deterministic and documented.

### 4) Strengthen server readiness semantics
**Where:**
- `src/embeddy/server/app.py`
- `src/embeddy/server/routes/health.py`

**Needed changes:**
- Health/readiness should clearly indicate model-ready state for local mode.
- Optional: add `/api/v1/readiness` or enrich `/api/v1/health` payload to include backend readiness.

### 5) Embeddy test coverage additions
**Where:**
- embeddy unit/integration tests (backend, CLI, server)

**Needed tests:**
- local backend load success/failure paths
- local encode path (dimension, normalization expectations)
- `embeddy serve` fails fast if local load fails
- env-only config path actually flips to remote/local correctly

## Change Map: remora-v2 (Integration Hardening)

### 1) Local search initialization robustness
**Where:**
- `/home/andrew/Documents/Projects/remora-v2/src/remora/core/services/search.py`

**Needed changes:**
- In `_initialize_local`, explicitly invoke embedder load if embeddy does not guarantee eager load.
- Catch embeddy-specific model load errors and set `available=False` with actionable logs.
- Consider validating collection creation/index readiness before reporting available=true.

### 2) API error handling for backend exceptions
**Where:**
- `/home/andrew/Documents/Projects/remora-v2/src/remora/web/routes/search.py`

**Needed changes:**
- Wrap `deps.search_service.search(...)` with structured exception mapping.
- Return JSON error responses (consistent `error_response`) instead of plain 500 text.
- Suggested mapping:
  - backend not ready/model load issue -> 503 (`search_backend_unavailable`)
  - malformed backend response -> 502/500 with stable error key

### 3) CLI indexing failure semantics
**Where:**
- `/home/andrew/Documents/Projects/remora-v2/src/remora/__main__.py` (`_index`)

**Needed changes:**
- Add strict mode (or default threshold) to fail if indexing returns per-file embedding errors.
- Improve error text to distinguish:
  - embeddy unreachable
  - embeddy reachable but model not ready
  - per-file indexing failures

### 4) remora-v2 test updates
**Where:**
- `/home/andrew/Documents/Projects/remora-v2/tests/unit/test_search.py`
- `/home/andrew/Documents/Projects/remora-v2/tests/integration/test_search_remote_backend.py`
- add new local-backend integration test module

**Needed tests:**
- local-mode initialize path with model-load failure -> service unavailable
- local-mode initialize path with model-load success -> search/index works
- `/api/search` returns structured JSON on backend exception
- `remora index` strict mode exits non-zero when embedding fails

### 5) docs/config guidance
**Where:**
- `/home/andrew/Documents/Projects/remora-v2/docs/HOW_TO_USE_REMORA.md`
- `remora.yaml.example`

**Needed changes:**
- Add explicit local-mode setup section:
  - required deps (torch/transformers/etc.)
  - resource expectations (CPU/GPU, RAM/VRAM)
  - startup verification steps

## Change Map: remora-test Demo Repo (After Upstream Fixes)

### 1) Remove temporary mock-embedder path from “primary” flow
**Where:**
- `configs/embeddy.remote.yaml`
- `scripts/mock_embedder_server.py`
- `README.md` troubleshooting section

**Needed changes:**
- Keep mock path only as fallback, not default strict path.
- Introduce local embeddy config (real model) as preferred setup.

### 2) Update test/ops scripts for local model workflow
**Where:**
- `scripts/test_search.sh`
- `scripts/run_demo_checks.sh` (if needed)

**Needed changes:**
- Better diagnostics for “model not loaded” vs “backend unreachable”.
- Optional preflight endpoint check for backend readiness.

### 3) Add local-mode startup helper (optional)
**Where:**
- new script, e.g. `scripts/start_search_local_stack.sh`

**Needed changes:**
- standardize startup order for local embeddy + remora runtime
- reduce manual misconfiguration risk during demo runs

## Recommended Delivery Order
1. **Embeddy upstream:** local backend implementation + startup load + env config fix + tests.
2. **remora-v2:** search service hardening + API error mapping + index strictness + tests.
3. **remora-test:** remove/fallback mock path, update scripts/docs to real local-model flow.
4. End-to-end validation across all three repos.

## Validation Checklist (Post-Implementation)
- `embeddy serve` local mode starts and reports ready.
- `embeddy /api/v1/embed` returns vectors in local mode.
- `devenv shell -- remora index --project-root .` indexes with zero model-load errors.
- `POST /api/search` returns 200 + valid JSON in hybrid mode.
- `REQUIRE_SEARCH=1 scripts/test_search.sh` passes without mock adapter.
- Existing non-search regressions remain green (`pytest` unit/integration suites).

## Risks / Open Questions
- Local model memory footprint may be too high for some dev machines.
- CPU-only embedding throughput may be too slow for strict demo checks.
- Multi-modal support scope for v1 local enablement (text-only first vs full parity).
- Whether embeddy should expose explicit readiness endpoint vs piggybacking health.
