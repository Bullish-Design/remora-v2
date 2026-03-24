# Demo V2 Update — Implementation Guide

> Detailed implementation guide for all 6 workstreams in NEXT_STEPS_REMORA_V2.md.
> Changes are upstream-only in `remora-v2`.

---

## Table of Contents

1. **[Execution Order and Dependencies](#1-execution-order-and-dependencies)** — Which workstreams depend on which, and the recommended sequence.

2. **[WS1: Harden Virtual Bundle Runtime Reliability](#2-ws1-harden-virtual-bundle-runtime-reliability)** — Reproduce Grail type-check failures, patch tool scripts, add input validation, guard against self-trigger loops.

3. **[WS2: Improve Event/Failure Observability](#3-ws2-improve-eventfailure-observability)** — Enrich event types with stable error fields, ensure tool start/success/failure and turn start/end/error are emitted consistently.

4. **[WS3: Offline-Safe Web UI Defaults](#4-ws3-offline-safe-web-ui-defaults)** — Vendor graphology and sigma JS libraries, update index.html, add static file serving for vendor assets.

5. **[WS4: Search and LSP Operator UX](#5-ws4-search-and-lsp-operator-ux)** — Standardize diagnostic messages for missing search/LSP dependencies, distinguish config errors from backend unreachability.

6. **[WS5: Upstream Regression Tests](#6-ws5-upstream-regression-tests)** — Test coverage for virtual agent reactive flows, tool-failure event payloads, offline web UI assets, and search/LSP diagnostics.

7. **[WS6: Upstream Documentation](#7-ws6-upstream-documentation)** — Update docs for virtual-agent architecture, event semantics, offline web UI, and search/LSP setup.

8. **[Commit Plan](#8-commit-plan)** — Suggested commit sequence aligned with workstreams.

---

## 1. Execution Order and Dependencies

### Dependency Graph

```
WS1 (Virtual Bundle Hardening)
 └──► WS2 (Event Observability)     — WS2 enriches events that WS1 error paths emit
       └──► WS5 (Regression Tests)  — tests validate WS1+WS2 behavior together

WS3 (Offline Web UI)                — independent of WS1/WS2
 └──► WS5 (Regression Tests)        — tests validate offline asset availability

WS4 (Search/LSP UX)                 — independent of WS1/WS2/WS3
 └──► WS5 (Regression Tests)        — tests validate diagnostic messages

WS5 (Regression Tests)              — depends on WS1, WS2, WS3, WS4
 └──► WS6 (Documentation)           — docs describe tested/guaranteed behavior
```

### Recommended Execution Sequence

| Phase | Workstreams | Rationale |
|-------|-------------|-----------|
| **Phase A** | WS1 + WS3 + WS4 (parallel) | Three independent implementation tracks. WS1 is the most complex and should start first. WS3 and WS4 are self-contained. |
| **Phase B** | WS2 | Depends on WS1 error paths being defined. Enriches events emitted during tool/turn failures. |
| **Phase C** | WS5 | Write regression tests once all behavior is implemented. |
| **Phase D** | WS6 | Document the guaranteed behavior after tests confirm it. |

### Estimated Complexity

| WS | Complexity | Files Touched | New Files |
|----|-----------|---------------|-----------|
| 1 | High | 6-8 | 0 |
| 2 | Medium | 3-5 | 0 |
| 3 | Low-Medium | 2-3 | 2-3 (vendored JS) |
| 4 | Low | 3-4 | 0 |
| 5 | Medium | 0-2 existing | 2-4 new test files |
| 6 | Low-Medium | 2-4 existing docs | 1-2 new doc pages |

---

## 2. WS1: Harden Virtual Bundle Runtime Reliability

### Problem Statement

Default virtual bundles (`review-agent`, `companion`) hit Grail type-check and tool execution failures during reactive turns triggered by `content_changed` / `turn_digested` events. Downstream demos had to fall back to "no-tools reactive" mode to remain stable.

### Root Cause Analysis Plan

#### Step 1: Reproduce the failure

1. Run `remora run` with default bundles on a small example project.
2. Trigger a `content_changed` event (edit a watched file).
3. Observe whether `review-agent` reactive turn completes or errors.
4. Capture the exact error from logs (look for `ToolError`, `GrailError`, or type-check messages).
5. Repeat for `companion` by waiting for `turn_digested` events.

Key log grep patterns:
```
grep -i "grail\|type.*check\|tool.*error\|incompatible" remora.log
```

#### Step 2: Isolate Grail type-check failures

The Grail runtime validates `@external` function signatures against the externals contract. Likely failure modes:

1. **Return type mismatch**: `.pym` declares `-> dict` but external returns `dict | None` (e.g., `graph_get_node` returning `None` for missing nodes).
2. **Input type coercion**: LLM passes string where int expected, or omits optional fields.
3. **Unhandled None in tool output**: Tool script assumes non-None return from `kv_get` or `graph_get_node`.

### Implementation Steps

#### 2.1 Patch `review-agent` tool scripts

**File: `src/remora/defaults/bundles/review-agent/tools/review_diff.pym`**

Current issue: `graph_get_node(node_id)` may return `None`, and the `@external` signature declares `-> dict`. The script handles `None` at runtime but the type contract may cause Grail to reject it.

Changes:
- Update `@external` return type to `-> dict | None` to match reality.
- Add defensive handling for missing `source_code` field:
  ```python
  current_source = node.get("source_code") or ""
  ```
- Truncate result output to prevent oversized tool results:
  ```python
  MAX_PREVIEW = 500
  # ... existing diff logic ...
  result = result[:2000]  # bound total output
  ```

**File: `src/remora/defaults/bundles/review-agent/tools/list_recent_changes.pym`**

Current issue: `graph_list_nodes()` returns `list[dict]` which should be safe, but node dicts may have missing keys.

Changes:
- Use `.get()` with fallbacks consistently (already done, verify).
- Bound output length (already shows first 20, verify total string length).

**File: `src/remora/defaults/bundles/review-agent/tools/submit_review.pym`**

Current issue: `send_message()` returns `dict[str, object]` — the `.get("sent")` and `.get("reason")` calls are safe but the `to_agent` parameter is `node_id` which may not match an active agent.

Changes:
- Add validation that `node_id` is non-empty before calling `send_message`.
- Handle case where `send_message` returns an unexpected shape:
  ```python
  if not isinstance(submitted, dict):
      result = f"Unexpected response from send_message: {type(submitted)}"
  ```

#### 2.2 Patch `companion` tool scripts

**File: `src/remora/defaults/bundles/companion/tools/aggregate_digest.pym`**

Current issue: `kv_get()` declared `-> object` — if it returns a string instead of a list/dict (e.g., from prior incompatible writes), `activity_log.append()` will fail.

Changes:
- Add type guards after `kv_get`:
  ```python
  activity_log = await kv_get("project/activity_log")
  if not isinstance(activity_log, list):
      activity_log = []
  ```
- Same pattern for `tag_frequency` (must be dict) and `agent_activity` (must be dict) and `insights` (must be list).
- Bound `summary` and `insight` input lengths to prevent KV bloat:
  ```python
  summary = summary[:500]
  insight = insight[:200]
  ```

#### 2.3 Harden bundle.yaml prompt contracts

**File: `src/remora/defaults/bundles/review-agent/bundle.yaml`**

Changes to `system_prompt_extension`:
- Add explicit instruction: "If a tool returns an error or None, report the issue briefly and stop — do not retry the same tool."
- Add: "Keep tool arguments concise. Pass only the required fields."
- Add: "Limit your response to under 1000 tokens."

**File: `src/remora/defaults/bundles/companion/bundle.yaml`**

Changes to `system_prompt`:
- Add: "If aggregate_digest fails, report the error briefly and stop."
- Add: "Do not call aggregate_digest more than once per reactive turn."
- Consider reducing `max_turns` from 3 to 2 (companion should be a single-shot observer).

#### 2.4 Guard against self-trigger loops

**File: `src/remora/core/agents/trigger.py`** (or wherever `TriggerPolicy` is defined)

The risk: `review-agent` emits an `agent_complete` event → triggers `companion` → companion emits `turn_digested` → could re-trigger `review-agent` if subscription rules overlap.

Investigation needed:
1. Read `TriggerPolicy` and `TriggerDispatcher` to understand current loop guards.
2. Check `src/remora/core/events/subscriptions.py` for subscription filtering.

Likely changes:
- Add `correlation_id` propagation so reactive turns inherit the originating event's correlation_id.
- Add a max-depth or max-reactive-turns-per-correlation-id guard in `TriggerDispatcher._route_to_actor()`.
- If a guard already exists in `ActorPool._handle_inbox_overflow()`, verify it covers the self-trigger case.

**File: `src/remora/core/agents/runner.py`**

In `_route_to_actor()`:
- Before enqueuing, check if the event's `correlation_id` has already triggered this agent N times (configurable, default 3).
- Log a warning and drop the event if the limit is reached.

#### 2.5 Ensure externals version compatibility

**File: `src/remora/defaults/bundles/review-agent/bundle.yaml`**
**File: `src/remora/defaults/bundles/companion/bundle.yaml`**

Both declare `externals_version: 2`. Verify:
1. Read `src/remora/core/tools/context.py` to confirm `EXTERNALS_VERSION >= 2`.
2. Ensure all `@external` functions used in the tool scripts are registered in the externals v2 contract.
3. Check `src/remora/core/tools/capabilities.py` for the external function registry.

### Acceptance Criteria

- [ ] `review-agent` completes a reactive turn on `content_changed` without ToolError/GrailError.
- [ ] `companion` completes a reactive turn on `turn_digested` without type errors.
- [ ] Self-trigger loops are bounded (max 3 reactive turns per correlation_id per agent).
- [ ] Tool scripts handle None/missing fields gracefully.
- [ ] No downstream "no-tools reactive" fallback is needed.

---

## 3. WS2: Improve Event/Failure Observability

### Problem Statement

Downstream validation scripts cannot reliably detect meaningful agent actions or diagnose failures from `/api/events` because:
1. Tool failure events lack structured error fields (class, reason, correlation_id).
2. Agent turn start/end/error events exist but error payloads are free-form strings.
3. The `/api/events` response shape is undocumented and may change.

### Current Event Landscape

From `src/remora/core/events/types.py`:

| Event | Error-relevant fields | Gap |
|-------|----------------------|-----|
| `AgentErrorEvent` | `error: str` | No error class, no structured reason |
| `RemoraToolCallEvent` | `tool_name`, `arguments_summary` | No result status |
| `RemoraToolResultEvent` | `is_error: bool`, `output_preview: str` | No error class/reason |
| `TurnCompleteEvent` | `errors_count: int` | No error details |

### Implementation Steps

#### 3.1 Enrich `RemoraToolResultEvent` with error details

**File: `src/remora/core/events/types.py`**

Add fields to `RemoraToolResultEvent`:
```python
class RemoraToolResultEvent(Event):
    event_type: str = EventType.REMORA_TOOL_RESULT
    agent_id: str
    tool_name: str
    is_error: bool = False
    error_class: str = ""       # NEW: e.g. "ToolError", "GrailError", "TypeError"
    error_reason: str = ""      # NEW: concise one-line reason
    duration_ms: int = 0
    output_preview: str = ""
    turn: int = 0
```

#### 3.2 Enrich `AgentErrorEvent` with structured fields

**File: `src/remora/core/events/types.py`**

Add fields to `AgentErrorEvent`:
```python
class AgentErrorEvent(Event):
    event_type: str = EventType.AGENT_ERROR
    agent_id: str
    error: str
    error_class: str = ""       # NEW: exception class name
    error_reason: str = ""      # NEW: concise reason (first line of error)
```

#### 3.3 Enrich `TurnCompleteEvent` with error summary

**File: `src/remora/core/events/types.py`**

Add field:
```python
class TurnCompleteEvent(Event):
    # ... existing fields ...
    error_summary: str = ""     # NEW: brief description of errors in this turn
```

#### 3.4 Emit enriched error fields from turn execution

**File: `src/remora/core/agents/turn.py`**

In `AgentTurnExecutor`, wherever `RemoraToolResultEvent` is emitted on error:
- Capture the exception class name: `type(exc).__name__`
- Capture a concise reason: `str(exc).split('\n')[0][:200]`
- Pass these as `error_class` and `error_reason`.

Similarly for `AgentErrorEvent` emission — populate `error_class` and `error_reason`.

For `TurnCompleteEvent` — if `errors_count > 0`, populate `error_summary` with a comma-separated list of error classes seen during the turn.

#### 3.5 Ensure correlation_id propagation

**File: `src/remora/core/agents/turn.py`** and **`src/remora/core/agents/actor.py`**

Verify that all events emitted during a reactive turn inherit the `correlation_id` from the triggering event. This is critical for downstream scripts to correlate tool failures back to the originating change event.

Check:
1. Does `AgentTurnExecutor` receive the triggering event's `correlation_id`?
2. Does it propagate it to all emitted events (`AgentStartEvent`, `RemoraToolCallEvent`, `RemoraToolResultEvent`, `TurnCompleteEvent`, `AgentCompleteEvent`, `AgentErrorEvent`)?
3. If not, thread it through from `Actor.run_turn()`.

#### 3.6 Stabilize `/api/events` response shape

**File: `src/remora/web/routes/events.py`**

Current implementation returns raw `event_store.get_events(limit=limit)` — the shape depends on what `EventStore.get_events()` returns.

Changes:
- Ensure each event in the response has a consistent envelope:
  ```json
  {
    "event_type": "remora_tool_result",
    "timestamp": 1711234567.89,
    "correlation_id": "abc-123",
    "tags": [],
    "payload": { ... event-specific fields ... }
  }
  ```
- Add optional `event_type` filter query parameter:
  ```
  GET /api/events?limit=50&event_type=remora_tool_result
  ```
- Add optional `correlation_id` filter:
  ```
  GET /api/events?correlation_id=abc-123
  ```

**File: `src/remora/core/events/store.py`**

Check `EventStore.get_events()` return shape. If it doesn't use `Event.to_envelope()`, add filtering support:
```python
async def get_events(
    self,
    limit: int = 50,
    event_type: str | None = None,
    correlation_id: str | None = None,
) -> list[dict]:
```

### Acceptance Criteria

- [ ] `RemoraToolResultEvent` includes `error_class` and `error_reason` when `is_error=True`.
- [ ] `AgentErrorEvent` includes `error_class` and `error_reason`.
- [ ] `TurnCompleteEvent` includes `error_summary` when `errors_count > 0`.
- [ ] All events in a reactive turn share the triggering event's `correlation_id`.
- [ ] `/api/events` supports `event_type` and `correlation_id` query filters.
- [ ] Downstream scripts can detect meaningful agent actions without log scraping.

---

## 4. WS3: Offline-Safe Web UI Defaults

### Problem Statement

`index.html` loads two JS libraries from unpkg CDN:
```html
<script src="https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"></script>
<script src="https://unpkg.com/sigma@3.0.0-beta.31/dist/sigma.min.js"></script>
```

In network-restricted environments, the page fails silently — the graph canvas never renders. Downstream demos had to patch `index.html` post-install.

### Current Static Serving Setup

From `src/remora/web/server.py`:
- `_STATIC_DIR = Path(__file__).parent / "static"` (line 31)
- `app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")` (line 103)
- `index.html` lives at `src/remora/web/static/index.html`

The `/static` mount already serves files from this directory, so vendored assets placed here will be served automatically.

### Implementation Steps

#### 4.1 Download and vendor JS libraries

Create directory: `src/remora/web/static/vendor/`

Download (one-time, checked into git):
```bash
curl -L -o src/remora/web/static/vendor/graphology.umd.min.js \
  "https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"

curl -L -o src/remora/web/static/vendor/sigma.min.js \
  "https://unpkg.com/sigma@3.0.0-beta.31/dist/sigma.min.js"
```

Verify file sizes are reasonable (graphology ~50KB, sigma ~150KB).

#### 4.2 Update `index.html` to use vendored assets

**File: `src/remora/web/static/index.html`**

Replace CDN script tags:
```html
<!-- Before -->
<script src="https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"></script>
<script src="https://unpkg.com/sigma@3.0.0-beta.31/dist/sigma.min.js"></script>

<!-- After -->
<script src="/static/vendor/graphology.umd.min.js"></script>
<script src="/static/vendor/sigma.min.js"></script>
```

#### 4.3 Include vendored files in package distribution

**File: `pyproject.toml`**

Ensure the `[tool.setuptools.package-data]` or equivalent includes `.js` files:
```toml
[tool.setuptools.package-data]
remora = ["web/static/**/*.js", "web/static/**/*.html", ...]
```

Or if using `hatchling`/other backend, check the equivalent inclusion mechanism. Verify with:
```bash
devenv shell -- python -c "from importlib.resources import files; print(list((files('remora') / 'web' / 'static' / 'vendor').iterdir()))"
```

#### 4.4 Optional: add fallback with CDN

For environments where CDN is preferred (smaller package, latest patches), add a fallback mechanism:

```html
<script src="/static/vendor/graphology.umd.min.js"></script>
<script>
  if (typeof graphology === 'undefined') {
    document.write('<script src="https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"><\/script>');
  }
</script>
```

**Recommendation**: Skip this. The vendored approach is simpler and more reliable. If users want CDN, they can modify `index.html` themselves.

### Acceptance Criteria

- [ ] `src/remora/web/static/vendor/graphology.umd.min.js` exists and is valid JS.
- [ ] `src/remora/web/static/vendor/sigma.min.js` exists and is valid JS.
- [ ] `index.html` references `/static/vendor/` paths, not CDN.
- [ ] Opening `/` works without internet access.
- [ ] Vendored JS files are included in package distribution.
- [ ] Graph renders correctly in the web UI.

---

## 5. WS4: Search and LSP Operator UX

### Problem Statement

When `remora[search]` or `remora[lsp]` extras are not installed, operators get opaque errors. The CLI and API paths don't clearly distinguish between:
1. **Missing dependency** — extra not installed (fixable by operator).
2. **Configuration error** — extra installed but config wrong (fixable by operator).
3. **Backend unreachable** — service down (transient/infra issue).

### Current State

**Search** (`src/remora/web/routes/search.py`):
- Returns 503 with `{"error": "Semantic search is not configured"}` when `search_service` is None or `not available`.
- No distinction between "embeddy not installed" vs "embeddy installed but backend unreachable".

**LSP** (`src/remora/lsp/__init__.py`):
- Raises `ImportError("LSP support requires pygls. Install with: pip install remora[lsp]")` — this is already pretty good but uses `pip install` instead of the correct `uv` command.

**CLI** (`src/remora/__main__.py`):
- Imports `create_lsp_server_standalone` at top level — if `pygls` is missing, import error happens at module load time, not at the `lsp` subcommand.

### Implementation Steps

#### 5.1 Improve search diagnostic messages

**File: `src/remora/web/routes/search.py`**

Replace the generic 503 with specific diagnostics:

```python
async def api_search(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.search_service is None:
        return JSONResponse(
            {
                "error": "search_not_configured",
                "message": "Semantic search is not configured. Install with: uv sync --extra search",
                "docs": "/docs/search-setup",
            },
            status_code=501,  # Not Implemented — feature not installed
        )
    if not deps.search_service.available:
        return JSONResponse(
            {
                "error": "search_backend_unavailable",
                "message": "Search backend is not reachable. Check embeddy connection.",
                "docs": "/docs/search-setup",
            },
            status_code=503,  # Service Unavailable — transient
        )
    # ... rest of handler
```

#### 5.2 Improve LSP diagnostic messages

**File: `src/remora/lsp/__init__.py`**

Update the error message:
```python
raise ImportError(
    "LSP support requires pygls. Install with: uv sync --extra lsp\n"
    "See docs/HOW_TO_USE_REMORA.md#lsp-setup for full setup instructions."
) from exc
```

**File: `src/remora/__main__.py`**

Move the `from remora.lsp import create_lsp_server_standalone` import from top-level to inside the `lsp` subcommand function, so the CLI doesn't crash at startup when pygls is missing:

```python
# Before (top-level):
from remora.lsp import create_lsp_server_standalone

# After (inside command):
@app.command()
def lsp(...):
    from remora.lsp import create_lsp_server_standalone
    # ...
```

If `lsp` is already a lazy import (check the actual command), verify it catches `ImportError` and prints a helpful message instead of a traceback.

#### 5.3 Add CLI `doctor` or `check` subcommand (optional, nice-to-have)

Add a `remora check` command that reports dependency status:

```
$ remora check
Remora v2.x.x
✓ Core dependencies OK
✗ Search: not installed (uv sync --extra search)
✗ LSP: not installed (uv sync --extra lsp)
✓ Web UI: static assets present
```

This is a stretch goal — skip if scope is too large.

#### 5.4 Standardize error response format across API

Ensure all API error responses follow a consistent shape:

```json
{
  "error": "error_code_snake_case",
  "message": "Human-readable description with fix instructions.",
  "docs": "/docs/relevant-page"    // optional
}
```

Review and update:
- `search.py` — done in step 5.1
- `events.py` — already uses `{"error": "invalid limit"}`, update to match format
- `nodes.py`, `chat.py`, etc. — audit for consistency

### Acceptance Criteria

- [ ] Search 501 response includes install instructions and distinguishes from 503.
- [ ] LSP import error message uses `uv sync` and references docs.
- [ ] CLI `lsp` command doesn't crash the entire CLI when pygls is missing.
- [ ] API error responses follow a consistent shape.
- [ ] Operators can resolve search/LSP issues from one error message.

---

## 6. WS5: Upstream Regression Tests

### Test Strategy

Tests should be structured to catch regressions in the four behavior guarantees:
1. Virtual agent reactive flows complete without errors.
2. Tool failure events contain structured error fields.
3. Web UI assets are available offline.
4. Missing dependency diagnostics are actionable.

### Implementation Steps

#### 6.1 Virtual agent reactive flow tests

**New file: `tests/unit/test_virtual_reactive_flow.py`**

Test scenarios:
1. **review-agent reactive turn on content_changed**: Mock the Grail tool execution and verify the turn completes without `ToolError` or `GrailError`.
2. **companion reactive turn on turn_digested**: Mock `kv_get`/`kv_set` externals and verify `aggregate_digest` tool completes cleanly.
3. **Self-trigger loop guard**: Emit events that would create a loop and verify the dispatcher drops events after max depth.
4. **Missing node handling**: Trigger `review_diff` with a `node_id` that doesn't exist in the graph store and verify graceful handling.

```python
import pytest
from remora.core.events.types import ContentChangedEvent, TurnDigestedEvent

# Test that review-agent tool scripts handle None return from graph_get_node
async def test_review_diff_missing_node(grail_runner):
    """review_diff.pym should return a message, not raise, when node is missing."""
    result = await grail_runner.execute(
        "review-agent", "review_diff",
        inputs={"node_id": "nonexistent"},
        externals={"graph_get_node": lambda _: None},
    )
    assert "not found" in result.lower()
    assert not grail_runner.had_errors
```

#### 6.2 Tool failure event payload tests

**New file: `tests/unit/test_event_error_fields.py`** (or extend `tests/unit/test_events.py`)

Test scenarios:
1. **RemoraToolResultEvent with error**: Verify `error_class` and `error_reason` are populated.
2. **AgentErrorEvent with structured fields**: Verify `error_class` and `error_reason`.
3. **TurnCompleteEvent error_summary**: Verify populated when `errors_count > 0`.
4. **correlation_id propagation**: Create a `ContentChangedEvent` with `correlation_id="test-123"` and verify all emitted events in the resulting turn share it.

```python
from remora.core.events.types import RemoraToolResultEvent

def test_tool_result_error_fields():
    evt = RemoraToolResultEvent(
        agent_id="test",
        tool_name="review_diff",
        is_error=True,
        error_class="ToolError",
        error_reason="node not found",
    )
    envelope = evt.to_envelope()
    assert envelope["payload"]["error_class"] == "ToolError"
    assert envelope["payload"]["error_reason"] == "node not found"
```

#### 6.3 Offline web UI asset tests

**New file: `tests/unit/test_web_static_assets.py`** (or extend `tests/unit/test_web_server.py`)

Test scenarios:
1. **Vendored JS files exist**: Assert `src/remora/web/static/vendor/graphology.umd.min.js` and `sigma.min.js` exist.
2. **index.html references local paths**: Parse `index.html` and assert no `unpkg.com` or external CDN URLs in `<script>` tags.
3. **Static file serving**: Use Starlette's `TestClient` to `GET /static/vendor/graphology.umd.min.js` and verify 200 response with JS content-type.

```python
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "remora" / "web" / "static"

def test_vendored_graphology_exists():
    assert (STATIC_DIR / "vendor" / "graphology.umd.min.js").is_file()

def test_vendored_sigma_exists():
    assert (STATIC_DIR / "vendor" / "sigma.min.js").is_file()

def test_no_cdn_references_in_index():
    html = (STATIC_DIR / "index.html").read_text()
    assert "unpkg.com" not in html
    assert "cdn." not in html.lower()
```

#### 6.4 Search/LSP diagnostic tests

**Extend: `tests/unit/test_search.py`** and **`tests/unit/test_views.py`** (or new file)

Test scenarios:
1. **Search not configured**: Mock `search_service=None`, call `/api/search`, assert 501 with `"search_not_configured"` error code.
2. **Search backend unavailable**: Mock `search_service.available=False`, call `/api/search`, assert 503 with `"search_backend_unavailable"`.
3. **LSP import error message**: Import `remora.lsp` with `pygls` unavailable, catch `ImportError`, assert message contains `uv sync --extra lsp`.
4. **API error response format consistency**: For each error endpoint, verify the response contains `"error"` and `"message"` keys.

### Acceptance Criteria

- [ ] `test_virtual_reactive_flow.py` covers review-agent and companion reactive turns.
- [ ] `test_event_error_fields.py` verifies structured error fields on failure events.
- [ ] `test_web_static_assets.py` catches missing vendored JS or CDN references.
- [ ] Search/LSP diagnostic tests verify actionable error messages.
- [ ] All new tests pass: `devenv shell -- pytest tests/unit/ -q`

---

## 7. WS6: Upstream Documentation

### Documentation Targets

| Doc | Location | Content |
|-----|----------|---------|
| Virtual agent architecture | `docs/virtual-agents.md` (new) | How review-agent and companion work, event triggers, tool contracts |
| Event semantics | `docs/event-semantics.md` (new) | Stable event fields, envelope format, error fields contract |
| Offline web UI | `docs/HOW_TO_USE_REMORA.md` (existing, new section) | Vendored assets, offline behavior, customization |
| Search/LSP setup | `docs/HOW_TO_USE_REMORA.md` (existing, new section) | Install instructions, troubleshooting matrix |

### Implementation Steps

#### 7.1 Virtual agent architecture doc

**New file: `docs/virtual-agents.md`**

Sections:
1. **Overview**: Virtual agents are bundle-defined agents (`NodeType.VIRTUAL`) that react to system events rather than being attached to specific code nodes.
2. **Default virtual agents**: `review-agent` (reacts to `content_changed`), `companion` (reacts to `turn_digested`).
3. **Reactive turn lifecycle**: Event → TriggerDispatcher → Actor inbox → AgentTurnExecutor → tools → events.
4. **Tool contracts**: List each tool in each bundle with its inputs, externals, and expected behavior.
5. **Loop guards**: How `correlation_id` propagation and max-reactive-turns prevent infinite loops.
6. **Customization**: How to modify/replace default bundles.

#### 7.2 Event semantics doc

**New file: `docs/event-semantics.md`**

Sections:
1. **Event envelope format**: The standard `{event_type, timestamp, correlation_id, tags, payload}` shape.
2. **Event type reference table**: Every `EventType` enum value with its payload fields.
3. **Error fields contract**: When `is_error=True` or `errors_count > 0`, which fields are guaranteed to be populated.
4. **Querying events via API**: `GET /api/events?limit=N&event_type=X&correlation_id=Y`.
5. **SSE stream**: `GET /sse` — event format, reconnection behavior.
6. **Scripting examples**: Python snippet to poll `/api/events` and detect review-agent actions.

#### 7.3 Update HOW_TO_USE_REMORA.md

**File: `docs/HOW_TO_USE_REMORA.md`**

Add sections:

**Offline Web UI**:
- Remora ships vendored JS assets — no internet required.
- Assets located at `src/remora/web/static/vendor/`.
- To update vendored libraries, download new versions and replace files.

**Search Setup**:
```
# Install search extra
uv sync --extra search

# Verify
remora check  # (if implemented)
# or
curl -X POST http://localhost:8765/api/search -d '{"query":"test"}'
# Expected: 200 with results, or 503 with "search_backend_unavailable"
```

Troubleshooting matrix:

| Symptom | HTTP Code | Cause | Fix |
|---------|-----------|-------|-----|
| `search_not_configured` | 501 | Extra not installed | `uv sync --extra search` |
| `search_backend_unavailable` | 503 | embeddy not running | Start embeddy, check connection |
| Connection refused | N/A | Web server not running | `remora run` |

**LSP Setup**:
```
# Install LSP extra
uv sync --extra lsp

# Verify
remora lsp --help
```

Troubleshooting:

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImportError: pygls` | Extra not installed | `uv sync --extra lsp` |
| LSP server crashes on start | Config issue | Check `remora.yaml` LSP section |

### Acceptance Criteria

- [ ] `docs/virtual-agents.md` describes architecture, tools, and loop guards.
- [ ] `docs/event-semantics.md` documents envelope format, all event types, and error field contracts.
- [ ] `docs/HOW_TO_USE_REMORA.md` has offline UI, search setup, and LSP setup sections.
- [ ] All doc references use correct file paths and API endpoints.

---

## 8. Commit Plan

Aligned with the phased execution order:

| # | Commit Message | Phase | Workstreams |
|---|---------------|-------|-------------|
| 1 | `fix(virtual): harden review-agent/companion reactive tool flows` | A | WS1 |
| 2 | `feat(web): vendor graph UI assets for offline-safe runtime` | A | WS3 |
| 3 | `fix(ux): improve search and lsp dependency diagnostics` | A | WS4 |
| 4 | `feat(events): standardize tool/turn failure event payloads` | B | WS2 |
| 5 | `test(regression): add reactive virtual-agent and offline-ui coverage` | C | WS5 |
| 6 | `docs: publish virtual/event/offline/search/lsp operational contracts` | D | WS6 |

### Commit Details

**Commit 1** (`fix(virtual)`):
- Modified: `review-agent/tools/*.pym`, `companion/tools/aggregate_digest.pym`
- Modified: `review-agent/bundle.yaml`, `companion/bundle.yaml`
- Modified: `core/agents/runner.py` or `core/events/dispatcher.py` (loop guard)

**Commit 2** (`feat(web)`):
- Added: `web/static/vendor/graphology.umd.min.js`, `web/static/vendor/sigma.min.js`
- Modified: `web/static/index.html`
- Modified: `pyproject.toml` (package-data, if needed)

**Commit 3** (`fix(ux)`):
- Modified: `web/routes/search.py`
- Modified: `lsp/__init__.py`
- Modified: `__main__.py`

**Commit 4** (`feat(events)`):
- Modified: `core/events/types.py`
- Modified: `core/agents/turn.py`
- Modified: `web/routes/events.py`
- Modified: `core/events/store.py`

**Commit 5** (`test(regression)`):
- Added: `tests/unit/test_virtual_reactive_flow.py`
- Added: `tests/unit/test_event_error_fields.py`
- Added: `tests/unit/test_web_static_assets.py`
- Modified: `tests/unit/test_search.py`, `tests/unit/test_views.py`

**Commit 6** (`docs`):
- Added: `docs/virtual-agents.md`
- Added: `docs/event-semantics.md`
- Modified: `docs/HOW_TO_USE_REMORA.md`

---

_End of implementation guide._
