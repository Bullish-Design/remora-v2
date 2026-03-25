# Test Suite Improvement Guide: Real-World Agent Coverage

> **Goal**: Every built-in agent bundle must have integration tests that hit the real
> vLLM server at `remora-server:8000`, exercise their actual tools (not toy
> stand-ins), and use Cairn workspaces for state persistence.

---

## Table of Contents

1. [Current State & Gap Summary](#1-current-state--gap-summary)
2. [Prerequisites & Environment Setup](#2-prerequisites--environment-setup)
3. [How the Existing Real-LLM Tests Work](#3-how-the-existing-real-llm-tests-work)
4. [Bug Fix: review-agent `graph_list_nodes` External](#4-bug-fix-review-agent-graph_list_nodes-external)
5. [Task A: companion Bundle Integration Test](#5-task-a-companion-bundle-integration-test)
6. [Task B: review-agent Bundle Integration Test](#6-task-b-review-agent-bundle-integration-test)
7. [Task C: test-agent Bundle Integration Test](#7-task-c-test-agent-bundle-integration-test)
8. [Task D: directory-agent Full Tool Coverage](#8-task-d-directory-agent-full-tool-coverage)
9. [Task E: system Bundle Extended Tool Coverage](#9-task-e-system-bundle-extended-tool-coverage)
10. [Task F: code-agent Extended Tool Coverage](#10-task-f-code-agent-extended-tool-coverage)
11. [Acceptance Test Additions](#11-acceptance-test-additions)
12. [Running the Full Suite](#12-running-the-full-suite)
13. [Checklist](#13-checklist)

---

## 1. Current State & Gap Summary

### What's tested with real LLM + Cairn today

| Bundle | File | What's covered |
|--------|------|----------------|
| system | `tests/integration/test_llm_turn.py` | `send_message`, `kv_get`, `kv_set` |
| code-agent | `tests/acceptance/test_live_runtime_real_llm.py` | `rewrite_self` (via proposal flow) |
| directory-agent | `tests/acceptance/test_live_runtime_real_llm.py` | reactive trigger only (no directory tools) |

### What has ZERO real-LLM coverage

| Bundle | Tools never exercised against vLLM | Priority |
|--------|-------------------------------------|----------|
| **companion** | `aggregate_digest` | P0 |
| **review-agent** | `list_recent_changes`, `review_diff`, `submit_review` | P0 |
| **test-agent** | `scaffold_test`, `suggest_tests` | P0 |

### Partially covered (specific tools missing)

| Bundle | Untested tools |
|--------|----------------|
| **directory-agent** | `list_children`, `broadcast_children`, `summarize_tree`, `get_parent` |
| **system** | `broadcast`, `ask_human`, `query_agents`, `reflect`, `semantic_search`, `categorize`, `companion_*`, `subscribe/unsubscribe`, `find_links` |
| **code-agent** | `scaffold`, `reflect`, `subscribe/unsubscribe` |

### Known bug found during analysis

`review-agent/tools/list_recent_changes.pym` calls `graph_list_nodes()` — this
external does **not exist** in `GraphCapabilities`. It will crash at runtime.
Must fix before writing tests. See [Task 4](#4-bug-fix-review-agent-graph_list_nodes-external).

---

## 2. Prerequisites & Environment Setup

### Environment variables

```bash
export REMORA_TEST_MODEL_URL="http://remora-server:8000/v1"
export REMORA_TEST_MODEL_NAME="Qwen/Qwen3-4B-Instruct-2507-FP8"
export REMORA_TEST_MODEL_API_KEY="EMPTY"
export REMORA_TEST_TIMEOUT_S="90"
```

### Running tests

Always use devenv:

```bash
# Run only the real_llm integration tests
devenv shell -- pytest tests/integration/test_llm_turn.py -m real_llm -v

# Run acceptance tests
devenv shell -- pytest tests/acceptance/ -m "acceptance and real_llm" -v

# Run everything including the new tests you'll write
devenv shell -- pytest tests/integration/test_llm_turn.py tests/acceptance/ -m real_llm -v
```

### Verify vLLM is reachable before starting

```bash
curl -s http://remora-server:8000/v1/models | python -m json.tool
```

You should see `Qwen/Qwen3-4B-Instruct-2507-FP8` in the model list.

---

## 3. How the Existing Real-LLM Tests Work

Every real-LLM test follows the same pattern. Study
`tests/integration/test_llm_turn.py` as the canonical reference.

### Pattern overview

```
1. Write temporary bundle files (bundle.yaml + tool .pym scripts)
2. Create a SQLite database + EventStore + NodeStore
3. Build a Config object pointing at the real vLLM URL
4. Create CairnWorkspaceService → initialize()
5. Run FileReconciler.full_scan() to discover nodes
6. Create an Actor for the target node
7. Build a Trigger + Outbox
8. Call actor._execute_turn(trigger, outbox)
9. Assert on events in EventStore (agent_start, agent_complete, agent_message, etc.)
10. Assert on workspace state (kv_get, file reads)
11. Cleanup: workspace_service.close(), db.close()
```

### Key helper: `_setup_llm_runtime`

Located at `tests/integration/test_llm_turn.py:243`. Reuse this for new tests.
It returns `(actor, node, event_store, workspace_service, db, source_path)`.

The `bundle_writer` parameter is a function you provide that writes the
bundle files your test needs. Each existing test has its own writer function
(e.g., `_write_llm_test_bundles`, `_write_kv_roundtrip_bundles`).

### What the .pym tool scripts do in tests

The test bundles write **simplified .pym scripts** that exercise specific
externals. They are NOT copies of the production bundles — they're minimal
scripts designed to make the LLM call a specific tool with predictable
arguments.

**For your new tests**: You have two options:

- **Option A (preferred)**: Use the **real production .pym files** from
  `src/remora/defaults/bundles/`. Copy them into the temp bundle directory.
  This tests the actual tool scripts agents use in production.

- **Option B**: Write simplified .pym scripts like the existing tests do.
  This is more deterministic but doesn't test the real tool code.

**Use Option A for all new tests.** The whole point is real-world coverage.

### How to copy production tools into test bundles

```python
import shutil
from pathlib import Path

DEFAULTS_BUNDLES = Path("src/remora/defaults/bundles")

def _write_companion_test_bundles(root: Path, model_name: str) -> None:
    """Copy the real companion bundle + system bundle into the test directory."""
    for bundle_name in ("system", "companion", "code-agent"):
        src = DEFAULTS_BUNDLES / bundle_name
        dst = root / bundle_name
        shutil.copytree(src, dst)
    # Override the model name in the companion bundle
    bundle_yaml = root / "companion" / "bundle.yaml"
    text = bundle_yaml.read_text()
    text = text.replace(
        'model: "Qwen/Qwen3-4B-Instruct-2507-FP8"',
        f'model: "{model_name}"',
    )
    bundle_yaml.write_text(text)
```

### Understanding Triggers

- **Chat triggers**: `AgentMessageEvent(from_agent="user", to_agent=node_id, content="...")`
  → Agent runs in "chat" mode with the `prompts.chat` template.
- **Reactive triggers**: `NodeChangedEvent(...)`, `ContentChangedEvent(...)`, or any
  non-user `AgentMessageEvent` → Agent runs in "reactive" mode with `prompts.reactive`.

For companion and review-agent, you'll use reactive triggers because they
respond to system events, not user chat.

---

## 4. Bug Fix: review-agent `graph_list_nodes` External

**File**: `src/remora/defaults/bundles/review-agent/tools/list_recent_changes.pym`

**Problem**: Line 9 declares `async def graph_list_nodes() -> list[dict]: ...`
but `GraphCapabilities` (in `src/remora/core/tools/capabilities.py`) has no
method called `graph_list_nodes`. It has `graph_query_nodes`.

**Fix**: Change `list_recent_changes.pym` to use the existing `graph_query_nodes`
external instead.

### Before (broken)

```python
# line 9
@external
async def graph_list_nodes() -> list[dict]: ...

# line 12
nodes = await graph_list_nodes()
```

### After (fixed)

```python
@external
async def graph_query_nodes(
    node_type: str | None = None,
    status: str | None = None,
    file_path: str | None = None,
) -> list[dict]: ...

nodes = await graph_query_nodes()
```

The rest of the script (`nodes[:MAX_ITEMS]` loop) works identically because
`graph_query_nodes()` returns `list[dict]` with the same shape.

**Do this fix FIRST before writing any review-agent tests.**

---

## 5. Task A: companion Bundle Integration Test

### What to test

The companion agent receives `turn_digested` events (reactive mode) and calls
`aggregate_digest` which uses `kv_get`/`kv_set` to maintain project-level
activity tracking.

### New file: `tests/integration/test_llm_companion.py`

### Test 1: `test_real_llm_companion_aggregate_digest_stores_activity`

**Setup**:
- Copy the real `companion/` and `system/` bundles into tmp_path
- Create a virtual node for the companion agent (NodeType.VIRTUAL, role="companion")
- Set up the runtime with `_setup_llm_runtime` or equivalent

**Trigger**:
```python
from remora.core.events.types import AgentCompleteEvent

# Simulate a turn_digested event arriving at the companion
trigger_event = AgentMessageEvent(
    from_agent="src/app.py::alpha",
    to_agent="companion",
    content=(
        "Turn digest: agent_id='src/app.py::alpha', "
        "summary='Explained the alpha function to user', "
        "tags='explanation,question'"
    ),
    correlation_id=correlation_id,
)
```

**System prompt override** — Override `companion/bundle.yaml` system_prompt to
make the LLM reliably call `aggregate_digest`:

```yaml
system_prompt: |
  You are the companion observer. When you receive a turn digest,
  call aggregate_digest exactly once with:
  - agent_id: the agent that completed the turn
  - summary: the digest summary
  - tags: comma-separated tags from the digest
  - insight: one short observation
  Then respond with one sentence.
```

**Assertions**:
1. `agent_start` and `agent_complete` events emitted (no `agent_error`)
2. Workspace KV store has data at `project/activity_log`:
   ```python
   workspace = await workspace_service.get_agent_workspace("companion")
   activity_log = await workspace.kv_get("project/activity_log")
   assert isinstance(activity_log, list)
   assert len(activity_log) >= 1
   assert activity_log[-1]["agent_id"] == "src/app.py::alpha"
   ```
3. `project/tag_frequency` has been populated:
   ```python
   tag_freq = await workspace.kv_get("project/tag_frequency")
   assert isinstance(tag_freq, dict)
   assert tag_freq.get("explanation", 0) > 0
   ```
4. `project/agent_activity` has an entry for `src/app.py::alpha`

### Test 2: `test_real_llm_companion_multiple_digests_accumulate`

Same setup, but fire TWO sequential triggers from different agents. Assert that
`project/activity_log` has 2 entries and `project/agent_activity` has 2 keys.

---

## 6. Task B: review-agent Bundle Integration Test

### Prerequisites

Complete the [bug fix in Task 4](#4-bug-fix-review-agent-graph_list_nodes-external) first.

### New file: `tests/integration/test_llm_review_agent.py`

### Test 1: `test_real_llm_review_agent_reviews_node_change`

**Setup**:
- Copy real `review-agent/`, `system/`, and `code-agent/` bundles
- Create a virtual node for review-agent (NodeType.VIRTUAL, role="review-agent")
- Ensure at least one function node exists (from FileReconciler.full_scan)

**System prompt override** for deterministic behavior:

```yaml
system_prompt: >-
  You are a code review agent. When triggered by a reactive event:
  1. Call list_recent_changes to see available nodes.
  2. Pick the first node_id from the results.
  3. Call review_diff with that node_id.
  4. Call submit_review with node_id, finding="Initial review recorded",
     severity="info", notify_user=false.
  Do not deviate from this sequence.
```

**Trigger**:
```python
trigger_event = NodeChangedEvent(
    node_id="src/app.py::alpha",
    old_hash="aaa",
    new_hash="bbb",
    file_path="src/app.py",
    correlation_id=correlation_id,
)
```

**Assertions**:
1. No `agent_error` events
2. `agent_complete` event present
3. At least one `agent_message` event (from `submit_review` → `send_message`)
4. Workspace KV has `review:previous_source:*` key (from `review_diff`)

### Test 2: `test_real_llm_review_agent_detects_diff_on_second_review`

- Run the review agent twice on the same node
- Between runs, change the node's source code
- Assert that the second `review_diff` call reports "Changes detected"
  (verify via workspace KV: the stored previous_source updates)

---

## 7. Task C: test-agent Bundle Integration Test

### New file: `tests/integration/test_llm_test_agent.py`

### Test 1: `test_real_llm_test_agent_suggests_tests_for_node`

**Setup**:
- Copy real `test-agent/`, `system/`, and `code-agent/` bundles
- Create virtual node for test-agent (NodeType.VIRTUAL, role="test-agent")
- Must have at least one function node

**System prompt override**:

```yaml
system_prompt: >-
  You are a test scaffolding agent. When triggered:
  1. Call suggest_tests with the node_id from the trigger event.
  2. Respond with one sentence summarizing the test suggestions.
  Do not call any other tools.
```

**Trigger**:
```python
trigger_event = NodeChangedEvent(
    node_id="src/app.py::alpha",
    old_hash="old",
    new_hash="new",
    file_path="src/app.py",
    correlation_id=correlation_id,
)
```

**Assertions**:
1. `agent_complete` present, no `agent_error`
2. The LLM successfully called `suggest_tests` (no tool errors in the turn)

### Test 2: `test_real_llm_test_agent_scaffolds_test`

Same setup, but system prompt tells agent to call `scaffold_test` with the
node_id and `test_type="unit"`.

**Assertions**:
1. `agent_complete` present, no `agent_error`
2. A `ScaffoldRequestEvent` custom event was emitted:
   ```python
   events = await event_store.get_events(limit=60)
   scaffold_events = [
       e for e in events
       if e["event_type"] == "ScaffoldRequestEvent"
   ]
   assert len(scaffold_events) >= 1
   assert scaffold_events[0]["payload"]["intent"].startswith("Create unit tests")
   ```

---

## 8. Task D: directory-agent Full Tool Coverage

### New file: `tests/integration/test_llm_directory_agent.py`

The existing acceptance test only verifies reactive trigger → `send_message`.
We need tests for the 4 directory-specific tools.

### Project setup (shared across all tests in this file)

Create a richer file structure so there are multiple nodes:

```python
def _write_directory_project(tmp_path: Path) -> None:
    write_file(tmp_path / "src" / "app.py", "def alpha():\n    return 1\n")
    write_file(tmp_path / "src" / "utils.py", "def beta():\n    return 2\n")
    write_file(tmp_path / "src" / "models" / "user.py", "class User:\n    pass\n")
```

This gives you:
- Directory nodes: `.`, `src`, `src/models`
- Function nodes: `src/app.py::alpha`, `src/utils.py::beta`
- Class node: `src/models/user.py::User`

### Test 1: `test_real_llm_directory_agent_list_children`

**System prompt override**:
```yaml
system_prompt: >-
  You manage a directory. When asked, call list_children exactly once,
  then call send_message with to_node_id="user" and content equal to
  the tool result. Do not call other tools.
```

**Trigger**: Chat message: "List your children."

**Assertions**:
1. `agent_complete`, no `agent_error`
2. An `agent_message` event to "user" exists, and its content mentions child node names

### Test 2: `test_real_llm_directory_agent_summarize_tree`

Same pattern. System prompt instructs: call `summarize_tree` with `max_depth=2`.
Assert the response mentions the nested directory structure.

### Test 3: `test_real_llm_directory_agent_get_parent`

Use the `src` directory node (not root). System prompt: call `get_parent`.
Assert the response mentions the root directory (`.`).

### Test 4: `test_real_llm_directory_agent_broadcast_children`

System prompt: call `broadcast_children` with message="ping".
Assert multiple `agent_message` events were emitted (one per child).

---

## 9. Task E: system Bundle Extended Tool Coverage

### New file: `tests/integration/test_llm_system_tools.py`

The existing tests cover `send_message` and `kv_get/set`. Add tests for:

### Test 1: `test_real_llm_system_broadcast`

- Create 3+ function nodes
- System prompt: call `broadcast` with pattern="*" and content="ping-all"
- Assert: multiple `agent_message` events emitted

### Test 2: `test_real_llm_system_query_agents`

- System prompt: call `query_agents` (which maps to `graph_query_nodes`)
  then call `send_message` to "user" with the count of nodes found
- Assert: `agent_message` to "user" with a number > 0

### Test 3: `test_real_llm_system_reflect`

The `reflect` tool writes notes to the workspace. Check the `reflect.pym`
script in `src/remora/defaults/bundles/system/tools/reflect.pym` to understand
what it writes, then:
- System prompt: call `reflect` with a specific note
- Assert: workspace file contains the note

### Test 4: `test_real_llm_system_subscribe_unsubscribe`

- System prompt: call `subscribe` for event_types=["node_changed"], then call
  `unsubscribe` with the returned subscription_id
- Assert: no errors, both calls succeed

**Note**: `ask_human` requires a `HumanInputBroker` which blocks waiting for
real human input. Testing this end-to-end requires wiring up a broker and
providing the response programmatically. This is a separate effort — skip for
now and add a TODO comment in the test file.

**Note**: `semantic_search` and `categorize` require the embeddings service
(embeddy). Skip these if embeddy is not available; add `skipif` markers.

---

## 10. Task F: code-agent Extended Tool Coverage

### Add to: `tests/integration/test_llm_turn.py` (or new file)

### Test 1: `test_real_llm_code_agent_reflect_writes_to_workspace`

- Use the real code-agent bundle
- System prompt: call `reflect` with note="test-reflection-note"
- Assert: workspace has the reflection stored

### Test 2: `test_real_llm_code_agent_subscribe_to_events`

- Use the real code-agent bundle
- System prompt: call `subscribe` for event_types=["node_changed"]
- Assert: subscription created successfully (no agent_error)

---

## 11. Acceptance Test Additions

Add these to `tests/acceptance/test_live_runtime_real_llm.py`.

### Test: `test_acceptance_companion_reacts_to_code_agent_complete`

Full-stack test:
1. Start RemoraLifecycle with companion virtual agent configured
2. Send a chat to a code-agent node
3. Code-agent completes → self-reflect fires → turn_digested emitted
4. Companion reacts → calls `aggregate_digest`
5. Assert: companion's `agent_complete` event appears in the event stream

This tests the **complete Layer 1 → Layer 2 reflection pipeline**.

### Test: `test_acceptance_review_agent_reacts_to_node_changed`

1. Start RemoraLifecycle with review-agent virtual agent subscribed to `node_changed`
2. Trigger a file change (rewrite + accept proposal, or direct file write + LSP didSave)
3. Assert: review-agent fires, calls `review_diff` + `submit_review`
4. Verify `agent_message` from review-agent appears in event stream

---

## 12. Running the Full Suite

### Run all real-LLM tests

```bash
REMORA_TEST_MODEL_URL="http://remora-server:8000/v1" \
devenv shell -- pytest \
    tests/integration/test_llm_turn.py \
    tests/integration/test_llm_companion.py \
    tests/integration/test_llm_review_agent.py \
    tests/integration/test_llm_test_agent.py \
    tests/integration/test_llm_directory_agent.py \
    tests/integration/test_llm_system_tools.py \
    tests/acceptance/test_live_runtime_real_llm.py \
    -m real_llm -v --timeout=120
```

### Run just the new tests

```bash
REMORA_TEST_MODEL_URL="http://remora-server:8000/v1" \
devenv shell -- pytest tests/integration/test_llm_companion.py -m real_llm -v
```

### Common failures and how to fix them

| Symptom | Cause | Fix |
|---------|-------|-----|
| `agent_error` with "unknown external" | Tool .pym calls an `@external` not in `TurnContext.to_capabilities_dict()` | Check the external name matches a method in `capabilities.py` |
| `agent_error` with model timeout | vLLM is slow or overloaded | Increase `REMORA_TEST_TIMEOUT_S` to 120+ |
| LLM doesn't call the expected tool | System prompt is too vague | Make the system prompt more imperative: "You MUST call X exactly once" |
| LLM calls tools with wrong arguments | Model is small (4B) and unreliable | Add argument examples in the system prompt |
| `KeyError: 'sent'` in send_message | Rate limiter kicked in | Set `send_message_limiter=None` in test config |

---

## 13. Checklist

Use this to track progress:

- [ ] **Bug fix**: `list_recent_changes.pym` — replace `graph_list_nodes` with `graph_query_nodes`
- [ ] **Task A**: companion `aggregate_digest` integration test (2 tests)
- [ ] **Task B**: review-agent `list_recent_changes` + `review_diff` + `submit_review` (2 tests)
- [ ] **Task C**: test-agent `suggest_tests` + `scaffold_test` (2 tests)
- [ ] **Task D**: directory-agent `list_children`, `summarize_tree`, `get_parent`, `broadcast_children` (4 tests)
- [ ] **Task E**: system `broadcast`, `query_agents`, `reflect`, `subscribe/unsubscribe` (4 tests)
- [ ] **Task F**: code-agent `reflect`, `subscribe` (2 tests)
- [ ] **Acceptance**: companion Layer 1→2 pipeline (1 test)
- [ ] **Acceptance**: review-agent reactive flow (1 test)
- [ ] Verify all tests pass: `devenv shell -- pytest -m real_llm -v`

**Total new tests: ~18**

### File summary

| New file | Tests |
|----------|-------|
| `tests/integration/test_llm_companion.py` | 2 |
| `tests/integration/test_llm_review_agent.py` | 2 |
| `tests/integration/test_llm_test_agent.py` | 2 |
| `tests/integration/test_llm_directory_agent.py` | 4 |
| `tests/integration/test_llm_system_tools.py` | 4 |
| `tests/integration/test_llm_turn.py` (additions) | 2 |
| `tests/acceptance/test_live_runtime_real_llm.py` (additions) | 2 |
