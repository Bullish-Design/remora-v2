# Virtual Agent Concept (Post-Consolidation)

## Purpose
Define a clean way to run agents that do not correspond to parsed CST code elements, while reusing the existing node/subscription/dispatch/actor runtime.

## Foundation
After consolidation, agent identity is already represented by `nodes.node_id`, and behavior comes from:
- `Node` row
- event subscriptions
- bundle role/prompt/tools

This enables non-CST agents without new tables or a parallel store.

## Core Design

### 1. Add a virtual node type
Extend `NodeType`:

```python
class NodeType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    SECTION = "section"
    TABLE = "table"
    DIRECTORY = "directory"
    VIRTUAL = "virtual"
```

### 2. Represent virtual agents as normal Node rows
Virtual agents are plain `Node` rows with code-location fields intentionally empty/defaulted:

```python
Node(
    node_id="test-agent",
    node_type=NodeType.VIRTUAL,
    name="test-agent",
    full_name="test-agent",
    file_path="",
    start_line=0,
    end_line=0,
    source_code="",
    source_hash="",
    parent_id=None,
    status=NodeStatus.IDLE,
    role="test-agent",
)
```

### 3. Declare virtual agents in config (not discovery)
Add a top-level `virtual_agents` section:

```yaml
virtual_agents:
  - id: "test-agent"
    role: "test-agent"
    subscriptions:
      - event_types: ["NodeChangedEvent", "NodeDiscoveredEvent"]
        path_glob: "tests/**"
      - event_types: ["NodeChangedEvent"]
        path_glob: "src/**"
```

Bootstrapping creates/updates these node rows and registers subscriptions.

### 4. Reuse existing subscription dispatch
No dispatcher changes required:
- subscription matching is string-ID based
- virtual IDs are matched and routed exactly like CST-backed node IDs

### 5. Prompt behavior for virtual nodes
`Actor._build_prompt()` should branch for `NodeType.VIRTUAL`:
- skip source-code framing
- inject role-centric framing from bundle identity/prompt
- keep existing message/event context wiring

### 6. Bundle-driven identity
Each virtual agent has a bundle (example: `bundles/test-agent/bundle.yaml`) defining:
- system prompt/persona
- tools
- reactive/chat prompts
- max turn policy

## Why This Is Clean
- No schema split: virtual and CST-backed agents share `nodes`
- No new store/service layer
- Existing event subscriptions, dispatcher, actor pool, and workspace model remain valid
- Declarative scale: add agents via config + bundle only

## Example Virtual Agents
- `test-agent`: monitors code change events and scaffolds tests
- `review-agent`: performs reactive code review on node changes
- `architecture-agent`: summarizes structural changes from node lifecycle events
- `docs-agent`: maintains docs in response to code changes
- `dependency-agent`: tracks import/dependency deltas

## Recommended Phase-2 Implementation Outline
1. Add `NodeType.VIRTUAL`.
2. Extend config schema with `virtual_agents`.
3. Add bootstrap path to upsert virtual nodes and apply subscriptions.
4. Add prompt branch in actor for virtual nodes.
5. Add bundles for first virtual agents (`test-agent`, `review-agent`).
6. Add integration tests:
   - bootstrap creates virtual nodes
   - subscriptions match path/event patterns
   - dispatch routes events to virtual actor
   - actor turn executes with virtual bundle prompt/tooling
