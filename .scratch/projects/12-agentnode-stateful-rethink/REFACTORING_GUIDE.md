# Refactoring Guide: Remora v2 Stateful Rethink

Each step is a self-contained PR. Steps are ordered so that earlier steps don't break the build, and later steps build on earlier ones. Each step lists affected files, what changes, and acceptance criteria.

**NO SUBAGENTS — all work must be done directly.**

## Table of Contents

1. **PR1: Migrate HumanChatEvent → AgentMessageEvent** — Remove HumanChatEvent, update web server and tests to use unified messaging.
2. **PR2: Remove AgentTextResponse** — User replies flow through send_message("user", ...) convention.
3. **PR3: Add Turn Modes (chat/reactive)** — Prompt-level mode injection based on trigger event type.
4. **PR4: Update Bundle YAML with Mode Prompts** — Add `prompts.chat` and `prompts.reactive` to bundle configs.
5. **PR5: Eliminate Stable Workspace Fallback (A2)** — Self-contained agent workspaces, no read-through to stable.db.
6. **PR6: Drop Companion Bundle, Merge into System (A5)** — Move companion tools to system bundle, delete companion bundle.
7. **PR7: Make Bundle System Purely Additive (A4 alternative)** — `bundle_name` means "also include these tools". System always included. Simplify provisioning.
8. **PR8: Structured Logging — Kill _preview_text (A10)** — Replace manual log formatting with structured JSON logging.
9. **PR9: Expose Workspace KV Store to Agents (A16)** — Add kv_get/kv_set externals and Grail tool wrappers.
10. **PR10: Event Envelope Middle Ground (A6)** — Typed event classes serialize to generic envelope. Clean up event hierarchy.
11. **PR11: Rename to Match Mental Model (A8)** — CodeNode→Node, AgentActor→Actor, AgentContext→TurnContext, etc.
12. **PR12: bundle.yaml as Plain Workspace File (A3)** — Stop treating bundle.yaml as special config; it's just a workspace file.

## Investigation Items (Not PRs — Research First)

- **I1: Collapse NodeStore + AgentStore (A1)** — Investigate whether merging makes sense given future non-CST node types.
- **I2: Separate Identity/Content/Runtime on Node (A14)** — Investigate field grouping or table normalization.
- **I3: fsdantic Overlay Semantics (A17)** — Verify fsdantic overlay API covers Remora's use cases before replacing AgentWorkspace.

---

## PR1: Migrate HumanChatEvent → AgentMessageEvent

### Motivation
`HumanChatEvent` is a separate event class that breaks the unified messaging model. User messages should be `AgentMessageEvent(from_agent="user", to_agent=node_id, content=message)` — the same as any other inter-entity communication.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/events/types.py` | Delete `HumanChatEvent` class. Remove from `__all__`. |
| `src/remora/core/events/__init__.py` | No change needed (star import picks up `__all__`). |
| `src/remora/web/server.py` | Change `api_chat()`: replace `HumanChatEvent(to_agent=node_id, message=message)` with `AgentMessageEvent(from_agent="user", to_agent=node_id, content=message)`. Update import. |
| `src/remora/core/actor.py` | In `_event_content()`: the `hasattr(event, "message")` branch becomes dead code after this. Remove it. The `AgentMessageEvent` has `.content`, so the `hasattr(event, "content")` branch already handles it. |
| `tests/unit/test_web_server.py` | Update chat test to verify `AgentMessageEvent` is emitted with `from_agent="user"`. |
| `tests/unit/test_events.py` | Remove any `HumanChatEvent`-specific tests. Add test that `AgentMessageEvent(from_agent="user")` works as user message. |
| `tests/unit/test_actor.py` | If any tests use `HumanChatEvent`, switch to `AgentMessageEvent(from_agent="user")`. |
| Any other test importing `HumanChatEvent` | Find with `grep -r HumanChatEvent tests/` and update. |

### Steps
1. Write a failing test: `test_api_chat_emits_agent_message_event` — POST to `/api/chat`, assert an `AgentMessageEvent` with `from_agent="user"` is emitted.
2. Update `web/server.py` to emit `AgentMessageEvent` instead of `HumanChatEvent`.
3. Delete `HumanChatEvent` from `events/types.py`.
4. Remove the `hasattr(event, "message")` fallback in `actor.py:_event_content()`.
5. Fix all test imports and assertions.
6. Run full test suite, verify green.

### Acceptance Criteria
- `HumanChatEvent` no longer exists anywhere in the codebase.
- `grep -r HumanChatEvent src/ tests/` returns nothing.
- The web API POST `/api/chat` emits `AgentMessageEvent(from_agent="user", to_agent=<id>, content=<msg>)`.
- All tests pass.

### Risk
Very low. Only 2 production uses of `HumanChatEvent` (import + `api_chat` endpoint). Subscription matching already works with `AgentMessageEvent` via `to_agent` pattern.

---

## PR2: Remove AgentTextResponse

### Motivation
With A13 (user replies via send_message convention), the node replies to the user by calling `send_message("user", response)`, which emits `AgentMessageEvent(from_agent=node_id, to_agent="user")`. The `AgentTextResponse` event type becomes unnecessary.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/events/types.py` | Delete `AgentTextResponse` class. Remove from `__all__`. |
| `src/remora/web/server.py` | SSE stream should surface `AgentMessageEvent` where `to_agent == "user"` as user-facing messages. No code change needed unless the frontend filters on event type. |
| `bundles/system/bundle.yaml` | Update system prompt to instruct: "When responding to a user message, use `send_message` to reply to 'user'." |
| Any file importing `AgentTextResponse` | Find with `grep -r AgentTextResponse src/ tests/` and remove. |

### Steps
1. Search for all usages: `grep -r AgentTextResponse`.
2. If any production code emits `AgentTextResponse`, replace with `send_message("user", ...)` via the existing `AgentMessageEvent` path.
3. Delete the class from `events/types.py`.
4. Update bundle system prompts to instruct agents to use `send_message("user", ...)` for user replies.
5. Run full test suite.

### Acceptance Criteria
- `AgentTextResponse` no longer exists in the codebase.
- The convention for user-facing replies is `AgentMessageEvent(to_agent="user")`.
- Bundle system prompts reference this convention.
- All tests pass.

### Risk
Low. `AgentTextResponse` appears to be unused in production code — the actor returns responses via `AgentCompleteEvent.result_summary`. This PR formalizes the `send_message("user", ...)` convention without changing runtime behavior.

---

## PR3: Add Turn Modes (chat/reactive)

### Motivation
Without mode awareness, every trigger produces the same behavior: conversational prose. Directory agents emit chatty summaries on file changes. System events waste tokens on narrative output.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/actor.py` | In `_execute_turn()`: after loading `bundle_config`, determine mode from trigger event. Inject mode prompt into system prompt. |

### Implementation Detail

In `_execute_turn()`, after `bundle_config = await self._read_bundle_config(workspace)`:

```python
# Determine turn mode from trigger event
mode = "chat"
if trigger.event is not None:
    from remora.core.events.types import AgentMessageEvent
    if isinstance(trigger.event, AgentMessageEvent) and trigger.event.from_agent == "user":
        mode = "chat"
    else:
        mode = "reactive"

# Load mode-specific prompt from bundle config
prompts = bundle_config.get("prompts", {})
mode_prompt = prompts.get(mode, "")

# Inject into system prompt
if mode_prompt:
    system_prompt = f"{system_prompt}\n\n{mode_prompt}"
```

**Note on isinstance**: REPO_RULES says "No isinstance in business logic" with an exception for "Projection dispatch (internal)." Mode determination is internal dispatch — it's the same pattern as projection dispatch. The `from_agent` field is on `AgentMessageEvent` only, so we need to check the type to safely access it. Alternative: use `getattr(trigger.event, "from_agent", None) == "user"` to avoid isinstance entirely.

Preferred approach (no isinstance):
```python
from_agent = getattr(trigger.event, "from_agent", None) if trigger.event else None
mode = "chat" if from_agent == "user" else "reactive"
```

### Steps
1. Write a failing test: `test_actor_chat_mode_injects_prompt` — trigger with `AgentMessageEvent(from_agent="user")`, verify system prompt includes chat mode instruction.
2. Write a failing test: `test_actor_reactive_mode_injects_prompt` — trigger with `ContentChangedEvent`, verify system prompt includes reactive mode instruction.
3. Implement mode determination and prompt injection in `_execute_turn`.
4. Run full test suite.

### Acceptance Criteria
- User messages trigger `chat` mode with chat-specific prompt injection.
- All other events trigger `reactive` mode with reactive-specific prompt injection.
- No new event types or code paths — just one `if` and one string lookup.
- All tests pass.

### Dependencies
- PR1 must be merged (so user messages are `AgentMessageEvent(from_agent="user")`).

---

## PR4: Update Bundle YAML with Mode Prompts

### Motivation
PR3 reads `prompts.chat` and `prompts.reactive` from bundle config. This PR adds those prompts to the actual bundle YAML files.

### Files Changed

| File | Change |
|------|--------|
| `bundles/system/bundle.yaml` | Add `prompts:` section with chat and reactive instructions. |
| `bundles/code-agent/bundle.yaml` | Add `prompts:` section tailored to code agents. |
| `bundles/directory-agent/bundle.yaml` | Add `prompts:` section tailored to directory agents. |
| `bundles/companion/bundle.yaml` | Add `prompts:` section (will be removed in PR6, but keep consistent until then). |

### Content

**system/bundle.yaml** prompts:
```yaml
prompts:
  chat: |
    A user is speaking to you. Respond helpfully and conversationally.
    Use your maintained state to provide grounded, accurate answers.
    If you need to reply, use the send_message tool to address "user".
  reactive: |
    System event received. Update your internal state files as needed.
    Do NOT produce narrative output. Focus on state maintenance.
```

**code-agent/bundle.yaml** prompts:
```yaml
prompts:
  chat: |
    A user is asking about this code element. Respond helpfully using
    your knowledge of this node's source, relationships, and context.
    Use send_message to reply to "user".
  reactive: |
    Source code or structure change detected. Update your state/ files
    to reflect new understanding. Do not produce conversational output.
```

**directory-agent/bundle.yaml** prompts:
```yaml
prompts:
  chat: |
    A user is asking about this directory. Respond with information about
    your children, structure, and organization. Use send_message to reply to "user".
  reactive: |
    Subtree change detected. Update your state/ files to reflect
    structural changes. Do not produce conversational output.
```

### Steps
1. Update each bundle YAML file with the `prompts:` section.
2. Write a test that loads each bundle config and verifies `prompts.chat` and `prompts.reactive` exist.
3. Run full test suite.

### Acceptance Criteria
- All bundle YAML files have `prompts.chat` and `prompts.reactive`.
- Mode prompts are concise and mode-appropriate.
- All tests pass.

### Dependencies
- PR3 (so the prompts are actually consumed).

---

## PR5: Eliminate Stable Workspace Fallback (A2)

### Motivation
The two-layer read-through (agent db → stable db) adds complexity to `AgentWorkspace`. Since bundle provisioning already copies templates into the agent workspace at provision time, the stable fallback is redundant. Each agent workspace should be self-contained.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/workspace.py` | **AgentWorkspace**: Remove `_stable` parameter and all fallback logic. `read()` just reads from `self._workspace`. `exists()` just checks `self._workspace`. `list_dir()` just lists from `self._workspace`. `list_all_paths()` just queries `self._workspace`. This removes ~60 lines of fallback code. |
| `src/remora/core/workspace.py` | **CairnWorkspaceService**: Remove `self._stable` field. Remove `await cairn_wm.open_workspace(...)` for stable. Remove `stable_workspace` parameter when constructing `AgentWorkspace`. `initialize()` just creates the agents directory. |
| `src/remora/core/workspace.py` | **CairnWorkspaceService.provision_bundle()**: Ensure it copies ALL template files (system + bundle-specific) into the agent workspace at provision time. This already happens — just verify. |
| `tests/unit/test_workspace.py` | Update tests: remove tests that verify stable fallback behavior. Add tests verifying self-contained workspace reads. |

### Implementation Detail

**AgentWorkspace** becomes:
```python
class AgentWorkspace:
    def __init__(self, workspace: Any, agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id
        self._lock = asyncio.Lock()

    async def read(self, path: str) -> str:
        async with self._lock:
            content = await self._workspace.files.read(path)
        return content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)

    async def write(self, path: str, content: str | bytes) -> None:
        async with self._lock:
            await self._workspace.files.write(path, content)

    async def exists(self, path: str) -> bool:
        async with self._lock:
            return await self._workspace.files.exists(path)

    async def list_dir(self, path: str = ".") -> list[str]:
        async with self._lock:
            return sorted(await self._workspace.files.list_dir(path, output="name"))

    async def delete(self, path: str) -> None:
        async with self._lock:
            await self._workspace.files.remove(path)

    async def list_all_paths(self) -> list[str]:
        async with self._lock:
            query = ViewQuery(path_pattern="**/*", recursive=True, include_stats=False, include_content=False)
            entries = await self._workspace.files.query(query)
            return sorted(str(getattr(e, "path", "")).lstrip("/") for e in entries if str(getattr(e, "path", "")).lstrip("/"))
```

**CairnWorkspaceService.initialize()** becomes:
```python
async def initialize(self) -> None:
    self._swarm_root.mkdir(parents=True, exist_ok=True)
    agents_root = self._swarm_root / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    # No stable workspace needed — each agent workspace is self-contained
```

### Steps
1. Write a failing test: workspace reads without stable fallback.
2. Simplify `AgentWorkspace` — remove all `_stable` references.
3. Simplify `CairnWorkspaceService` — remove stable workspace initialization.
4. Update `get_agent_workspace` to not pass `stable_workspace`.
5. Verify `provision_bundle` still copies all templates into agent workspace.
6. Update/remove workspace tests that relied on stable fallback.
7. Run full test suite.

### Acceptance Criteria
- `AgentWorkspace` has no reference to a stable workspace.
- `CairnWorkspaceService` does not create or manage a stable workspace.
- Each agent workspace is self-contained with all bundle files copied in at provision time.
- All tests pass.
- `workspace.py` is significantly shorter (~60 fewer lines).

### Risk
Low. Provisioning already copies templates into agent workspaces. The stable fallback is a safety net that's never actually needed in practice. Startup re-provisioning (via `sync_existing_bundles`) ensures updated templates propagate.

---

## PR6: Drop Companion Bundle, Merge into System (A5)

### Motivation
The companion bundle (`reflect.pym`, `categorize.pym`, `find_links.pym`, `summarize.pym`) contains reflection/maintenance tools that are useful for any node type. They should be system tools, not a separate bundle.

### Files Changed

| File | Change |
|------|--------|
| `bundles/system/tools/` | Copy `reflect.pym`, `categorize.pym`, `find_links.pym`, `summarize.pym` from `bundles/companion/tools/`. |
| `bundles/companion/` | Delete entire directory. |
| `src/remora/core/config.py` | Remove `"companion"` from default `bundle_mapping` if present. |
| `tests/unit/test_companion_tools.py` | Update tool paths in tests (they should now load from `bundles/system/tools/`). Or rename to `test_reflection_tools.py`. |

### Steps
1. Copy companion tools to system bundle.
2. Delete companion bundle directory.
3. Remove any config references to companion bundle.
4. Update tests.
5. Run full test suite.

### Acceptance Criteria
- `bundles/companion/` no longer exists.
- All companion tools are available in `bundles/system/tools/`.
- No references to "companion" in config or bundle mapping.
- All tests pass.

---

## PR7: Make Bundle System Purely Additive (A4 alternative)

### Motivation
Clarify the bundle system: the system bundle is always included, and `bundle_name` means "also include tools from this directory." Make this explicit rather than implicit.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/config.py` | Rename `bundle_mapping` to make the additive nature clear. Document that system is always included. |
| `src/remora/code/reconciler.py` | In `_provision_bundle()`: already does `template_dirs = [bundle_root / "system"]` + optional bundle dir. Just add a comment making this explicit. |
| `src/remora/code/projections.py` | Same — provisioning already works additively. |
| `bundles/system/bundle.yaml` | Update system prompt to be the universal base prompt. |
| `bundles/code-agent/bundle.yaml` | Remove `system_prompt` — the system bundle provides the base. Only keep `prompts:` overrides and code-specific tools. |
| `bundles/directory-agent/bundle.yaml` | Same — remove `system_prompt`, keep only directory-specific overrides. |

### Implementation Detail

The key insight is that this is mostly already how it works. The refactoring is about making it explicit:

1. The system bundle's `bundle.yaml` provides the base system prompt for ALL nodes.
2. A role-specific bundle (code-agent, directory-agent) provides ONLY:
   - Additional tools (in its `tools/` directory).
   - `prompts:` overrides for mode-specific behavior.
   - Optionally, a `system_prompt_extension:` that gets appended to the system prompt.

This means `bundle.yaml` loading in the actor should:
1. Always read `_bundle/bundle.yaml` (which comes from the system bundle).
2. If a role-specific bundle also provides a `bundle.yaml`, merge its fields (not replace).

### Steps
1. Update system bundle.yaml to be the universal base.
2. Update code-agent and directory-agent bundle.yaml to provide only additive config.
3. Update `_read_bundle_config` in actor.py if needed to support merged config.
4. Update provisioning to copy system bundle.yaml first, then overlay role-specific bundle.yaml.
5. Run full test suite.

### Acceptance Criteria
- System bundle provides the universal base configuration.
- Role-specific bundles provide only additional tools and prompt overrides.
- The additive nature is explicit in code and config.
- All tests pass.

### Risk
Medium. Need to be careful about the merge semantics when two bundle.yaml files both define `system_prompt`. The resolution should be: system bundle provides base, role bundle extends.

---

## PR8: Structured Logging — Kill _preview_text (A10)

### Motivation
`_preview_text()` in `actor.py` manually formats log messages by replacing newlines. The `_preview()` function in `grail.py` does similar. Use structured logging instead.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/actor.py` | Remove `_preview_text()`. Use `logging` with `extra=` for structured fields instead of string interpolation. Or switch to JSON formatter. |
| `src/remora/core/grail.py` | Remove `_preview()`. Use structured logging. |
| `src/remora/__main__.py` | Configure JSON log formatter as an option (e.g., `--log-format json`). |

### Implementation Detail

Option A (simpler): Just remove the `_preview_text` / `_preview` functions and log the raw values. The log formatter handles presentation.

Option B (more complete): Add a JSON formatter class:
```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data)
```

Recommend Option A for this PR. JSON formatting can be a follow-up if needed.

### Steps
1. Remove `_preview_text` from `actor.py`. Replace calls with direct value logging.
2. Remove `_preview` from `grail.py`. Replace calls with direct value logging.
3. Run full test suite.

### Acceptance Criteria
- No manual log-formatting helper functions in the codebase.
- Log messages include full payloads without truncation or newline replacement.
- All tests pass.

---

## PR9: Expose Workspace KV Store to Agents (A16)

### Motivation
fsdantic workspaces expose a KV store (`workspace.kv.get/set/delete/list`) that Remora doesn't use. Exposing this gives agents typed, structured state persistence alongside the file API.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/workspace.py` | **AgentWorkspace**: Add `kv_get`, `kv_set`, `kv_delete`, `kv_list` methods that delegate to `self._workspace.kv`. |
| `src/remora/core/externals.py` | **AgentContext**: Add `kv_get`, `kv_set`, `kv_delete`, `kv_list` external methods. Add them to `to_externals_dict()`. |
| `bundles/system/tools/` | Add `kv_get.pym` and `kv_set.pym` Grail tools. |
| `tests/unit/test_workspace.py` | Add tests for KV operations on workspace. |
| `tests/unit/test_externals.py` | Add tests for KV externals. |

### Implementation Detail

**AgentWorkspace KV methods**:
```python
async def kv_get(self, key: str) -> str | None:
    async with self._lock:
        return await self._workspace.kv.get(key)

async def kv_set(self, key: str, value: str) -> None:
    async with self._lock:
        await self._workspace.kv.set(key, value)

async def kv_delete(self, key: str) -> None:
    async with self._lock:
        await self._workspace.kv.delete(key)

async def kv_list(self, prefix: str = "") -> list[str]:
    async with self._lock:
        return await self._workspace.kv.list(prefix=prefix)
```

**Note**: The exact fsdantic KV API needs verification against the Cairn codebase. The methods above are approximate — check `workspace.kv` interface before implementing.

### Steps
1. Verify fsdantic KV store API by reading Cairn's `external_functions.py` usage.
2. Write failing tests for KV operations on workspace.
3. Implement KV methods on `AgentWorkspace`.
4. Write failing tests for KV externals on `AgentContext`.
5. Implement KV externals and add to `to_externals_dict()`.
6. Create `kv_get.pym` and `kv_set.pym` Grail tools.
7. Run full test suite.

### Acceptance Criteria
- Agents can read/write structured data to the KV store via externals.
- Grail tools exist for KV operations.
- KV data persists across turns (verified by test).
- All tests pass.

### Dependencies
- PR5 should be merged first (simplified workspace), but not strictly required.

---

## PR10: Event Envelope Middle Ground (A6)

### Motivation
12 event classes create a large surface area. The "middle ground" keeps typed Python classes for developer ergonomics but ensures they all serialize to a generic envelope for storage and dispatch.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/events/types.py` | Ensure all event classes inherit from `Event` (already true). Add `to_envelope()` method on `Event` base that returns `{"event_type": str, "timestamp": float, "correlation_id": str|None, "payload": dict}`. Remove `HumanChatEvent` and `AgentTextResponse` (already done in PR1/PR2). Clean up any remaining dead event types. |
| `src/remora/core/events/store.py` | `append()` already serializes via `event.model_dump()`. No change needed — the envelope format is just the serialized form. |

### Implementation Detail

The "middle ground" is actually mostly in place already — events serialize to dicts for storage, and dispatch works on `event_type` strings. This PR is about:

1. Cleaning up after PR1/PR2 (removing dead imports/references).
2. Adding a `to_envelope()` convenience method if useful.
3. Ensuring the `__all__` exports are minimal and clean.
4. Documenting the convention: "Event subclasses are for Python ergonomics; the event log stores generic envelopes."

### Steps
1. Clean up `events/types.py` — remove dead classes, update `__all__`.
2. Add `to_envelope()` method to `Event` base if useful for external consumers.
3. Update any code that does manual event type introspection.
4. Run full test suite.

### Acceptance Criteria
- Event type hierarchy is clean (no dead classes).
- All events serialize cleanly to a generic envelope.
- `__all__` exports reflect the actual live event types.
- All tests pass.

### Dependencies
- PR1 and PR2 must be merged first.

---

## PR11: Rename to Match Mental Model (A8)

### Motivation
Several names leak implementation details or use jargon from upstream libraries. Renaming reduces cognitive load for developers encountering Remora for the first time.

### Renames

| Current | New | Affected Files |
|---------|-----|---------------|
| `CodeNode` | `Node` | `node.py`, `graph.py`, `actor.py`, `externals.py`, `reconciler.py`, `projections.py`, `lsp/server.py`, all tests |
| `CodeElement` | `DiscoveredElement` | `node.py`, `projections.py`, tests |
| `CSTNode` | `DiscoveredElement` (or keep as `CSTNode` — it IS from tree-sitter) | `discovery.py`, `projections.py`, `reconciler.py`, tests |
| `AgentActor` | `Actor` | `actor.py`, `runner.py`, tests |
| `AgentContext` | `TurnContext` | `externals.py`, `actor.py`, tests |
| `AgentRunner` | `ActorPool` | `runner.py`, `services.py`, `__main__.py`, tests |
| `bundle_name` (field) | `role` | `node.py`, `config.py`, `reconciler.py`, `projections.py`, tests, bundle yamls |
| `swarm_root` (config) | `workspace_root` | `config.py`, `workspace.py`, `__main__.py`, `remora.yaml` |
| `externals` (dict) | `capabilities` | `externals.py`, `grail.py`, `actor.py`, tests |

### Implementation Strategy

This is the largest PR. Do it as a series of find-and-replace operations, one rename at a time:

1. `CodeNode` → `Node` (most widespread)
2. `AgentActor` → `Actor`
3. `AgentContext` → `TurnContext`
4. `AgentRunner` → `ActorPool`
5. `bundle_name` → `role` (field name on model + config + DB column)
6. `swarm_root` → `workspace_root`
7. `externals` → `capabilities` (parameter/variable names, not the `to_externals_dict` method which becomes `to_capabilities_dict`)

**DB migration note**: The `bundle_name` column rename and `swarm_root` config rename need careful handling:
- SQLite `ALTER TABLE RENAME COLUMN` works for `bundle_name` → `role`.
- Config files (`remora.yaml`) need the new key name. Keep old name as deprecated alias.

### Steps
1. One rename at a time, with full test suite run after each.
2. Start with the safest renames (class names with no DB impact).
3. End with DB-impacting renames (field names that map to columns).
4. Run full test suite after each rename.

### Acceptance Criteria
- All names match the mental model table above.
- No references to old names remain (except backward-compat aliases where needed).
- DB schema is updated.
- All tests pass.

### Risk
Medium-high due to breadth. Mitigate by doing one rename at a time. Consider splitting into sub-PRs if the diff is too large.

### Dependencies
- All prior PRs should be merged to minimize merge conflicts.

---

## PR12: bundle.yaml as Plain Workspace File (A3)

### Motivation
`_read_bundle_config()` in `actor.py` treats `bundle.yaml` as special configuration. But it's already a workspace file — the actor reads it via `workspace.read("_bundle/bundle.yaml")`. The only "special" treatment is parsing it as YAML and extracting `system_prompt`, `model`, and `max_turns`.

### Files Changed

| File | Change |
|------|--------|
| `src/remora/core/actor.py` | `_read_bundle_config()` stays but becomes the canonical way to read node config. Add validation: if YAML parse fails or required fields missing, use defaults. |
| `bundles/*/bundle.yaml` | Add comment: "This file is readable and writable by the node at runtime." |

### Implementation Detail

This PR is minimal because bundle.yaml is *already* a workspace file. The refactoring is conceptual:

1. Document that nodes CAN modify their own `bundle.yaml` via `write_file("_bundle/bundle.yaml", ...)`.
2. Add validation in `_read_bundle_config()` so that bad config doesn't crash the actor.
3. The system prompt, model, max_turns, and mode prompts are all stored in this file — making it the single source of node personality configuration.

What this enables:
- A node could modify its own system prompt based on learning.
- A node could switch its model to a more powerful one for complex tasks.
- External tooling could modify a node's config by writing to its workspace.

### Steps
1. Add validation to `_read_bundle_config()` — handle malformed YAML, missing fields.
2. Add a test: write modified bundle.yaml to workspace, verify actor reads new config on next turn.
3. Document the convention in bundle YAML comments.
4. Run full test suite.

### Acceptance Criteria
- `_read_bundle_config()` handles malformed config gracefully.
- A test verifies that workspace-modified config is picked up on next turn.
- All tests pass.

### Dependencies
- PR4 (mode prompts in bundle YAML) and PR7 (additive bundle system) should be merged first.

---

## Investigation Items

### I1: Collapse NodeStore + AgentStore (A1)

**Question**: Should we merge NodeStore and AgentStore into one store?

**For merging**: Eliminates synchronization bugs (dual-transition in actor.py:322-338). Removes `_ensure_agent()` pattern. One fewer concept.

**Against merging**: The user noted "What about nodes that aren't CST nodes? Might want to create a ResearchNode or something?" If future node types don't map 1:1 to discovered code elements, the separation might be useful.

**Investigation steps**:
1. List all fields on `Agent` that aren't already on `CodeNode`. Answer: none — `Agent` has `agent_id`, `element_id`, `status`, `bundle_name`, all of which exist on `CodeNode`.
2. Consider future node types: would a "ResearchNode" or "ConversationNode" need agent-specific fields not shared with code nodes?
3. If yes: keep separation but add a shared `status` field to avoid dual-transition.
4. If no: merge into one model/table.

**Recommendation**: Keep them separate for now. The future node type concern is valid. Instead, fix the dual-transition problem by making `AgentStore` the sole authority for status and removing status from `CodeNode`/`NodeStore`.

### I2: Separate Identity/Content/Runtime on Node (A14)

**Question**: Should CodeNode/Node be split into conceptual or physical groups?

**Investigation steps**:
1. Profile: how often does status change vs. source content vs. identity? Status changes every turn (IDLE→RUNNING→IDLE). Source changes on file edit. Identity changes never.
2. Count write amplification: each status transition writes the full `CodeNode` row (14 fields) when only `status` changes.
3. Consider: would splitting into `node_identity` + `node_content` + `node_runtime` tables help?
4. Consider: would just using `UPDATE nodes SET status = ? WHERE node_id = ?` (which is what `set_status` already does) be sufficient?

**Recommendation**: The existing `set_status()` method already does targeted updates. No table split needed. Just fix the dual-transition by removing one of the stores from status management (see I1).

### I3: fsdantic Overlay Semantics (A17)

**Question**: Can fsdantic's overlay API replace the hand-rolled `AgentWorkspace` overlay logic?

**Investigation steps**:
1. Read fsdantic overlay API: `workspace.overlay.merge/list_changes/reset`.
2. Verify it supports: merged directory listings, path queries, exists checks.
3. Check if overlay is between two workspaces or within one.
4. If overlay is between workspaces: could replace the stable→agent fallback pattern.
5. But PR5 eliminates the fallback entirely, so this becomes moot unless we find other uses.

**Recommendation**: Defer. PR5 eliminates the stable workspace fallback, removing the primary use case for overlay semantics. If future needs arise (e.g., node state review/approval workflow), revisit then.

---

## Execution Order Summary

```
PR1 (HumanChatEvent → AgentMessageEvent)
  ↓
PR2 (Remove AgentTextResponse)
  ↓
PR3 (Add Turn Modes) ← depends on PR1
  ↓
PR4 (Bundle Mode Prompts) ← depends on PR3
  ↓
PR5 (Eliminate Stable Workspace) ← independent, can parallel with PR3/PR4
  ↓
PR6 (Drop Companion Bundle) ← independent
  ↓
PR7 (Additive Bundle System) ← depends on PR6
  ↓
PR8 (Structured Logging) ← independent
  ↓
PR9 (KV Store Externals) ← depends on PR5
  ↓
PR10 (Event Envelope Cleanup) ← depends on PR1, PR2
  ↓
PR11 (Rename Everything) ← depends on all above
  ↓
PR12 (bundle.yaml as Workspace File) ← depends on PR4, PR7
```

Parallelizable groups:
- **Group A** (event model): PR1 → PR2 → PR10
- **Group B** (turn behavior): PR3 → PR4
- **Group C** (workspace): PR5 → PR9
- **Group D** (bundles): PR6 → PR7 → PR12
- **Group E** (cleanup): PR8

PR11 (renaming) goes last because it touches everything.

---

**NO SUBAGENTS — all work must be done directly.**
