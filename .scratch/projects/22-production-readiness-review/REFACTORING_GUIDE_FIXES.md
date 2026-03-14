# Remora v2 — Refactoring Guide: Existing Codebase Fixes

**Date:** 2026-03-14
**Scope:** Step-by-step guide to fix all identified issues in the current codebase
**Prerequisite:** Read CODE_REVIEW.md for full issue context
**Test command:** `devenv shell -- pytest tests/`

---

## Table of Contents

1. [Fix `remora.yaml` Missing Directory Overlay](#1-fix-remorayayaml-missing-directory-overlay) — Add `directory: "directory-agent"` to bundle_overlays so directory agents receive their tools
2. [Fix `rewrite_self.pym` Misleading Messaging](#2-fix-rewrite_selfpym-misleading-messaging) — Return distinct success/failure messages instead of ambiguous `f"Rewrite applied: {success}"`
3. [Fix LSP Stdout Corruption](#3-fix-lsp-stdout-corruption) — Redirect logging to stderr when `--lsp` is active to prevent JSON-RPC stream corruption
4. [Fix Agent Response Truncation](#4-fix-agent-response-truncation) — Remove 200-char hard truncation on `AgentCompleteEvent.result_summary`
5. [Add `--bind` Option for Web Server](#5-add---bind-option-for-web-server) — Make web server bind address configurable for tailnet access
6. [Fix Event Bus Error Handling](#6-fix-event-bus-error-handling) — Add exception logging for failed async event handlers
7. [Fix SSE Replay Format Consistency](#7-fix-sse-replay-format-consistency) — Normalize replayed event payloads to match live SSE event structure
8. [Improve Grail Tool Descriptions](#8-improve-grail-tool-descriptions) — Extract meaningful descriptions from Grail scripts instead of generic `"Tool: {name}"`
9. [Add LLM Retry Logic](#9-add-llm-retry-logic) — Single retry with backoff for transient kernel failures
10. [Add Type Annotations to LSP Server Factory](#10-add-type-annotations-to-lsp-server-factory) — Replace `Any` params on `create_lsp_server` with concrete types
11. [Clean Up `web/server.py` Dead Parameter](#11-clean-up-webserverpy-dead-parameter) — Remove discarded `project_root` parameter or implement its intended use

---

## 1. Fix `remora.yaml` Missing Directory Overlay

**Severity:** Medium | **Effort:** 5 minutes | **Risk:** None

### Problem

The shipped `remora.yaml` (line 12-16) is missing the `directory: "directory-agent"` overlay that exists in `remora.yaml.example` (line 15). This means directory nodes get provisioned with the system bundle only — they lack directory-specific tools like `list_children.pym`, `broadcast_children.pym`, `summarize_tree.pym`, and `get_parent.pym`.

### File

`remora.yaml` — line 12-16

### Current Code

```yaml
bundle_overlays:
  function: "code-agent"
  class: "code-agent"
  method: "code-agent"
  file: "code-agent"
```

### Fix

```yaml
bundle_overlays:
  function: "code-agent"
  class: "code-agent"
  method: "code-agent"
  file: "code-agent"
  directory: "directory-agent"
```

### Test

```bash
devenv shell -- pytest tests/unit/test_workspace.py -v
```

After fix, run `remora discover` and verify directory nodes exist, then check their workspace `_bundle/tools/` contains the directory-agent tools.

---

## 2. Fix `rewrite_self.pym` Misleading Messaging

**Severity:** Low | **Effort:** 10 minutes | **Risk:** None

### Problem

`bundles/code-agent/tools/rewrite_self.pym` (line 11) returns `f"Rewrite applied: {success}"` which produces the string `"Rewrite applied: False"` on failure — misleading since the word "applied" suggests success.

### File

`bundles/code-agent/tools/rewrite_self.pym` — lines 10-12

### Current Code

```python
success = await apply_rewrite(new_source)
message = f"Rewrite applied: {success}"
message
```

### Fix

```python
success = await apply_rewrite(new_source)
if success:
    message = "Rewrite applied successfully."
else:
    message = "Rewrite failed: the source could not be applied."
message
```

### Test

```bash
devenv shell -- pytest tests/unit/test_grail.py -v
```

If no existing test covers this specific tool's output, verify manually by inspecting the tool output in logs during an agent turn.

---

## 3. Fix LSP Stdout Corruption

**Severity:** Critical | **Effort:** 30 minutes | **Risk:** Low

### Problem

When `--lsp` is active, `lsp_server.start_io` reads stdin/writes stdout for JSON-RPC. But `_configure_logging` (`__main__.py` line 255-259) installs a `StreamHandler` on the root logger that writes to stdout. Any log message corrupts the JSON-RPC stream, crashing the neovim LSP client.

### File

`src/remora/__main__.py` — `_configure_logging()` (lines 246-259) and `start_command()` (line 71)

### Fix

Pass the `lsp` flag to `_configure_logging` and redirect the stream handler to stderr when LSP mode is active:

```python
def _configure_logging(level_name: str, *, lsp_mode: bool = False) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise typer.BadParameter(f"Invalid log level: {level_name}")
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.handlers:
        return

    import sys
    stream = sys.stderr if lsp_mode else sys.stdout
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger.addHandler(stream_handler)
```

Update the call site in `start_command()` (line 71):

```python
_configure_logging(log_level, lsp_mode=lsp)
```

### Test

```bash
devenv shell -- pytest tests/unit/test_cli.py -v
```

Add a unit test that verifies when `lsp_mode=True`, the stream handler writes to stderr:

```python
def test_configure_logging_lsp_mode_uses_stderr():
    import sys
    _configure_logging("INFO", lsp_mode=True)
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)
                       and not isinstance(h, logging.FileHandler)]
    assert any(h.stream is sys.stderr for h in stream_handlers)
```

### Verification

After fix, start `remora start --lsp` and connect neovim. The LSP client should initialize without JSON parse errors. Logging output should appear on stderr (visible in terminal) rather than corrupting the LSP channel.

---

## 4. Fix Agent Response Truncation

**Severity:** High | **Effort:** 1 hour | **Risk:** Low

### Problem

`core/actor.py` line 389 truncates the agent's response to 200 characters:

```python
result_summary=response_text[:200],
```

This means the full agent response is lost from the event stream. The `AgentCompleteEvent` carries almost no useful content.

### File

`src/remora/core/actor.py` — `_complete_agent_turn()` method, line 389

### Fix

Two-part fix:

**Part A — Store full response in AgentCompleteEvent:**

In `core/events/types.py`, add a `full_response` field to `AgentCompleteEvent`:

```python
class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""
    full_response: str = ""

    def summary(self) -> str:
        return self.result_summary
```

**Part B — Populate both fields in actor.py:**

In `core/actor.py` `_complete_agent_turn()`:

```python
await outbox.emit(
    AgentCompleteEvent(
        agent_id=node_id,
        result_summary=response_text[:200],
        full_response=response_text,
        correlation_id=trigger.correlation_id,
    )
)
```

The `result_summary` stays truncated for log display, but `full_response` preserves the complete text for UI display and downstream processing.

### Test

```bash
devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_events.py -v
```

Add a test that verifies `full_response` is populated:

```python
async def test_agent_complete_event_preserves_full_response():
    long_text = "x" * 500
    event = AgentCompleteEvent(agent_id="test", result_summary=long_text[:200], full_response=long_text)
    assert len(event.full_response) == 500
    assert len(event.result_summary) == 200
```

---

## 5. Add `--bind` Option for Web Server

**Severity:** Critical | **Effort:** 30 minutes | **Risk:** None

### Problem

`__main__.py` line 172 hardcodes `host="127.0.0.1"`. For tailnet access where the user browses from another machine, the server must bind to `0.0.0.0` or a specific interface.

### File

`src/remora/__main__.py` — lines 169-176

### Fix

Add a `--bind` CLI option:

```python
BIND_ARG = typer.Option(
    "--bind",
    help="Address to bind the web server to (use 0.0.0.0 for all interfaces).",
)
```

Add to `start_command` signature:

```python
bind: Annotated[str, BIND_ARG] = "127.0.0.1",
```

Pass to `_start`:

```python
asyncio.run(
    _start(
        ...,
        bind=bind,
    )
)
```

Update `_start` to accept and use `bind`:

```python
async def _start(
    *,
    ...
    bind: str = "127.0.0.1",
) -> None:
    ...
    logger.info("Starting web server on %s:%d", bind, port)
    web_config = uvicorn.Config(
        web_app,
        host=bind,
        port=port,
        log_level="warning",
        access_log=False,
    )
```

### Test

```bash
devenv shell -- pytest tests/unit/test_cli.py -v
```

Verify by running `remora start --bind 0.0.0.0 --port 8080` and confirming access from another tailnet host.

---

## 6. Fix Event Bus Error Handling

**Severity:** Medium | **Effort:** 30 minutes | **Risk:** None

### Problem

`core/events/bus.py` `_dispatch_handlers` (lines 27-36) creates asyncio tasks for coroutine handlers and gathers them, but doesn't handle exceptions from those tasks. A failing handler produces an unhandled exception warning in the asyncio task.

### File

`src/remora/core/events/bus.py` — `_dispatch_handlers()`, lines 27-36

### Current Code

```python
@staticmethod
async def _dispatch_handlers(
    handlers: list[EventHandler], event: Event
) -> None:
    tasks: list[asyncio.Task[Any]] = []
    for handler in handlers:
        result = handler(event)
        if asyncio.iscoroutine(result):
            tasks.append(asyncio.create_task(result))
    if tasks:
        await asyncio.gather(*tasks)
```

### Fix

Add `return_exceptions=True` to gather and log any errors:

```python
@staticmethod
async def _dispatch_handlers(
    handlers: list[EventHandler], event: Event
) -> None:
    tasks: list[asyncio.Task[Any]] = []
    for handler in handlers:
        result = handler(event)
        if asyncio.iscoroutine(result):
            tasks.append(asyncio.create_task(result))
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.exception(
                    "Event handler failed for %s: %s",
                    event.event_type,
                    result,
                    exc_info=result,
                )
```

Add the logger import at the top of the file:

```python
import logging

logger = logging.getLogger(__name__)
```

### Test

```bash
devenv shell -- pytest tests/unit/test_event_bus.py -v
```

Add a test that verifies a failing handler doesn't crash the bus:

```python
async def test_failing_handler_does_not_crash_bus():
    bus = EventBus()
    calls = []

    async def bad_handler(event):
        raise ValueError("boom")

    async def good_handler(event):
        calls.append(event)

    bus.subscribe_all(good_handler)
    bus.subscribe_all(bad_handler)

    event = AgentStartEvent(agent_id="test")
    await bus.emit(event)
    assert len(calls) == 1  # good_handler still ran
```

---

## 7. Fix SSE Replay Format Consistency

**Severity:** Medium | **Effort:** 1 hour | **Risk:** Low

### Problem

In `web/server.py` SSE stream (lines 94-117), replayed events include `event_type` in the JSON payload (line 102-103) while live events use `event.model_dump()` which also includes `event_type` — but the surrounding envelope structure differs. Replayed events manually build an envelope with `timestamp` and `correlation_id` at the top level plus merged payload fields. Live events dump the full Pydantic model.

This means the same SSE event name can have different JSON structures depending on whether it was replayed or live.

### File

`src/remora/web/server.py` — `sse_stream()`, lines 94-117

### Fix

Normalize replay format to match `event.to_envelope()` structure, or — simpler — normalize live events to use `to_envelope()` too:

```python
# Live events — use to_envelope() for consistent structure
async with event_bus.stream() as stream:
    async for event in stream:
        if await request.is_disconnected():
            break
        payload = json.dumps(event.to_envelope(), separators=(",", ":"))
        yield f"event: {event.event_type}\ndata: {payload}\n\n"
```

For replay, keep the existing envelope construction but ensure it matches:

```python
# Replay events — already in envelope format from DB
for row in reversed(rows):
    event_name = row.get("event_type", "Event")
    payload_text = json.dumps(row, separators=(",", ":"))
    yield f"event: {event_name}\ndata: {payload_text}\n\n"
```

The key insight: the DB already stores events in envelope format via `to_envelope()`. So just pass through the DB row as-is for replay, and use `to_envelope()` for live events, and both will be consistent.

### Test

```bash
devenv shell -- pytest tests/unit/test_web_server.py -v
```

Add a test that verifies replay and live SSE events have the same top-level keys.

---

## 8. Improve Grail Tool Descriptions

**Severity:** Medium | **Effort:** 2-3 hours | **Risk:** Low

### Problem

`core/grail.py` line 78 sets `description=f"Tool: {script.name}"` for every tool. The LLM gets no information about what the tool does, just its name. For a 4B parameter model, this severely impacts tool selection quality.

### File

`src/remora/core/grail.py` — `GrailTool.__init__()`, line 78

### Fix

**Option A — Extract from Grail script source (preferred):**

Grail scripts are Python-like files. Extract the first docstring or comment block as the description:

```python
def _extract_description(script: grail.GrailScript, source: str | None = None) -> str:
    """Extract a tool description from the script source or metadata."""
    # Check if script has a docstring attribute
    if hasattr(script, 'docstring') and script.docstring:
        return script.docstring.strip()

    # Fall back to parsing first comment/docstring from source
    if source:
        lines = source.strip().splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#') and not stripped.startswith('#!'):
                return stripped.lstrip('# ').strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                # Simple single-line docstring extraction
                quote = stripped[:3]
                if stripped.count(quote) >= 2:
                    return stripped[3:stripped.index(quote, 3)].strip()
                break
            if stripped and not stripped.startswith('from ') and not stripped.startswith('import '):
                break

    return f"Tool: {script.name}"
```

**Option B — Add description comments to existing .pym files:**

Add a header comment to each tool file, e.g. in `rewrite_self.pym`:

```python
# Rewrite this code element's source code with the provided new_source.
from grail import Input, external
...
```

Then update the description extraction to use these comments.

**Update GrailTool constructor and discover_tools:**

Pass the source to `GrailTool` so it can extract the description:

```python
class GrailTool:
    def __init__(
        self,
        script: grail.GrailScript,
        *,
        capabilities: dict[str, Any] | None = None,
        name_override: str | None = None,
        agent_id: str = "?",
        source_file: str | None = None,
        source: str | None = None,
    ):
        ...
        self._schema = ToolSchema(
            name=name_override or script.name,
            description=_extract_description(script, source),
            parameters=_build_parameters(script),
        )
```

Update `discover_tools`:

```python
tools.append(
    GrailTool(
        script=script,
        capabilities=resolved_capabilities,
        agent_id=agent_id,
        source_file=filename,
        source=source,
    )
)
```

### Existing .pym Tool Descriptions to Add

| Tool File | Description |
|-----------|-------------|
| `send_message.pym` | Send a message to another agent or to 'user' for chat responses. |
| `query_agents.pym` | Query the node graph for agents matching filters (type, status, path). |
| `rewrite_self.pym` | Rewrite this code element's source code with the provided new_source. |
| `broadcast.pym` | Broadcast a message to all agents matching a path glob pattern. |
| `reflect.pym` | Write a reflection note to persistent workspace storage for future reference. |
| `kv_get.pym` | Read a value from the agent's persistent key-value store. |
| `kv_set.pym` | Write a value to the agent's persistent key-value store. |
| `subscribe.pym` | Subscribe this agent to events matching specified types and path patterns. |
| `unsubscribe.pym` | Remove a subscription from this agent. |
| `list_children.pym` | List all child nodes in this directory. |
| `broadcast_children.pym` | Send a message to all child nodes in this directory. |
| `summarize_tree.pym` | Summarize the directory tree structure below this node. |
| `get_parent.pym` | Get information about this node's parent directory node. |
| `scaffold.pym` | Create scaffolding files in the agent's workspace. |
| `categorize.pym` | Categorize this code element by purpose and domain. |
| `find_links.pym` | Find related links and references for this code element. |
| `summarize.pym` | Generate a summary of this agent's workspace and context. |

### Test

```bash
devenv shell -- pytest tests/unit/test_grail.py -v
```

Add a test verifying description extraction from source comments.

---

## 9. Add LLM Retry Logic

**Severity:** Medium | **Effort:** 1 hour | **Risk:** Low

### Problem

`core/kernel.py` `create_kernel()` and `core/actor.py` `_run_kernel()` have no retry logic. A single transient failure (timeout, connection reset, vLLM restart) kills the entire agent turn. During a demo, this is catastrophic.

### File

`src/remora/core/actor.py` — `_run_kernel()`, lines 341-375

### Fix

Add retry logic in `_run_kernel()`. One retry with exponential backoff:

```python
async def _run_kernel(
    self,
    node_id: str,
    trigger: Trigger,
    system_prompt: str,
    messages: list[Message],
    model_name: str,
    tools: list[GrailTool],
    max_turns: int,
) -> Any:
    max_retries = 1
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        kernel = create_kernel(
            model_name=model_name,
            base_url=self._config.model_base_url,
            api_key=self._config.model_api_key,
            timeout=self._config.timeout_s,
            tools=tools,
        )
        try:
            tool_schemas = [tool.schema for tool in tools]
            if attempt == 0:
                logger.info(
                    (
                        "Model request node=%s corr=%s base_url=%s model=%s "
                        "tools=%s system=%s user=%s"
                    ),
                    node_id,
                    trigger.correlation_id,
                    self._config.model_base_url,
                    model_name,
                    [schema.name for schema in tool_schemas],
                    system_prompt,
                    messages[1].content or "",
                )
            else:
                logger.warning(
                    "Retrying model request node=%s attempt=%d/%d",
                    node_id,
                    attempt + 1,
                    max_retries + 1,
                )
            return await kernel.run(messages, tool_schemas, max_turns=max_turns)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                backoff = 2.0 ** attempt
                logger.warning(
                    "Model request failed node=%s attempt=%d, retrying in %.1fs: %s",
                    node_id,
                    attempt + 1,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
            else:
                raise
        finally:
            await kernel.close()

    raise last_exc  # unreachable, but satisfies type checker
```

### Test

```bash
devenv shell -- pytest tests/unit/test_actor.py -v
```

Add a test that mocks `kernel.run` to fail once then succeed, verifying the retry fires.

---

## 10. Add Type Annotations to LSP Server Factory

**Severity:** Low | **Effort:** 15 minutes | **Risk:** None

### Problem

`lsp/server.py` line 50: `create_lsp_server(node_store, event_store)` uses untyped parameters (`# noqa: ANN001`). The API contract is unclear.

### File

`src/remora/lsp/server.py` — line 50

### Current Code

```python
def create_lsp_server(node_store, event_store) -> LanguageServer:  # noqa: ANN001
```

### Fix

```python
from remora.core.graph import NodeStore
from remora.core.events.store import EventStore

def create_lsp_server(node_store: NodeStore, event_store: EventStore) -> LanguageServer:
```

Remove the `# noqa: ANN001` comment.

### Test

```bash
devenv shell -- pytest tests/unit/test_lsp_server.py -v
```

No behavior change — this is purely a type annotation fix.

---

## 11. Clean Up `web/server.py` Dead Parameter

**Severity:** Low | **Effort:** 10 minutes | **Risk:** None

### Problem

`web/server.py` line 29: `del project_root` — the parameter is accepted but immediately discarded. Either remove it or use it.

### File

`src/remora/web/server.py` — lines 21-29

### Fix

Since `project_root` is unused and no current feature needs it, remove it from the signature. Update the caller in `__main__.py` accordingly.

**In `web/server.py`:**

```python
def create_app(
    event_store: Any,
    node_store: Any,
    event_bus: Any,
) -> Starlette:
    """Create Starlette app exposing graph APIs, events, and chat."""
```

**In `__main__.py`** (lines 163-168):

```python
web_app = create_app(
    services.event_store,
    services.node_store,
    services.event_bus,
)
```

Remove the `project_root=project_root` keyword argument.

### Test

```bash
devenv shell -- pytest tests/unit/test_web_server.py -v
```

Verify all existing test calls to `create_app` still work (they may need `project_root` kwarg removed if present).

---

*End of Refactoring Guide: Existing Codebase Fixes*
