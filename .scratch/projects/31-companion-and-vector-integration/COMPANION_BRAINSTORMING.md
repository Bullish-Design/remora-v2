# Companion System Integration — Brainstorming

## Table of Contents

1. [What the v1 Companion System Actually Did](#1-what-the-v1-companion-system-actually-did)
   - 1.1 Core Components
   - 1.2 Data Flow
   - 1.3 What Mattered vs. What Was Noise
2. [v2 Primitives We Already Have](#2-v2-primitives-we-already-have)
   - 2.1 Actor Model
   - 2.2 Event System
   - 2.3 Workspace (Cairn + KV)
   - 2.4 TurnContext API
   - 2.5 Virtual Agents
   - 2.6 Bundle System
3. [Design Principle: Post-Turn Hooks, Not Swarms](#3-design-principle-post-turn-hooks-not-swarms)
   - 3.1 Why v1's MicroSwarm Approach Was Over-Engineered
   - 3.2 The Simpler Alternative: Hook Pipeline
   - 3.3 Hook Definition via Bundle Config
4. [Design: Post-Turn Hook Pipeline](#4-design-post-turn-hook-pipeline)
   - 4.1 Hook Protocol
   - 4.2 Built-in Hooks
   - 4.3 Integration Point in Actor
   - 4.4 Configuration
5. [Design: Agent Memory via Workspace KV](#5-design-agent-memory-via-workspace-kv)
   - 5.1 Conversation Indexing
   - 5.2 Agent Notes / Reflections
   - 5.3 Tags and Categories
   - 5.4 Cross-Agent Links
   - 5.5 Memory in System Prompt
6. [Design: Sidebar / Summary Composition](#6-design-sidebar-summary-composition)
   - 6.1 What "Sidebar" Means in v2
   - 6.2 Composition as a Virtual Agent
   - 6.3 Web API Integration
7. [Concrete Implementation Plan](#7-concrete-implementation-plan)
   - 7.1 Files to Create
   - 7.2 Files to Modify
   - 7.3 Configuration Changes
   - 7.4 Event Types to Add
8. [Alternative Approaches Considered](#8-alternative-approaches-considered)

---

## 1. What the v1 Companion System Actually Did

### 1.1 Core Components

The v1 companion system had five major pieces:

1. **NodeAgent** (`companion/node_agent.py`) — A persistent, per-CST-node chat agent. Maintained conversation history (`list[NodeMessage]`), responded to cursor focus / content changes / file saves / inter-agent messages. On each `send()`, it ran an LLM turn, persisted the exchange to workspace files, then kicked off MicroSwarms as a background task.

2. **MicroSwarms** (`companion/swarms/`) — Four parallel post-exchange processors:
   - **SummarizerSwarm**: Ran an LLM call to produce a one-sentence summary of the exchange, saved to a chat index in the workspace.
   - **CategorizerSwarm**: Ran an LLM call to tag the exchange with 1-3 tags from a predefined list (bug, refactor, explanation, etc.), saved to the chat index.
   - **LinkerSwarm**: Pattern-matched the exchange text to find cross-node references (e.g., `test_foo` mentioned → creates a "tested_by" link), saved to `links.json` in workspace.
   - **ReflectionSwarm**: Ran an LLM call to extract one concrete insight from the exchange, appended to `notes/agent_notes.md` in workspace.

3. **Sidebar Composer** (`companion/sidebar/composer.py`) — Read workspace state (user notes, agent notes, chat index, links, workspace panels) and composed a single markdown document for display in the editor sidebar.

4. **NodeAgentRouter** (`companion/router.py`) — Event router that created/retrieved NodeAgent instances on CursorFocus/ContentChanged/FileSaved events and delegated to the appropriate handler.

5. **IndexingService** (`companion/indexing_service.py`) — Embeddy integration for vector search across code. (Covered separately in VECTOR_BRAINSTORMING.md.)

### 1.2 Data Flow

```
User cursor → CursorFocusEvent → NodeAgentRouter → NodeAgent.on_cursor_focus()
                                                    → compose_sidebar() → emit SidebarReady

User chat msg → NodeAgent.send()
                → LLM turn (with workspace-enriched system prompt)
                → persist exchange to workspace
                → spawn background MicroSwarms:
                    ├─ SummarizerSwarm → update chat index
                    ├─ CategorizerSwarm → tag chat index entry
                    ├─ LinkerSwarm → update links.json
                    └─ ReflectionSwarm → append to agent_notes.md
                → compose_sidebar() → emit SidebarReady
```

### 1.3 What Mattered vs. What Was Noise

**High value:**
- Agent memory persisted across sessions (chat summaries, reflections, notes in workspace)
- System prompt enriched with accumulated agent knowledge
- Post-turn processing to distill knowledge from exchanges

**Medium value:**
- Chat index with summaries and tags (useful for history browsing)
- Cross-agent link discovery (helps build the knowledge graph)

**Low value / over-engineered:**
- Separate NodeAgent class duplicating what Actor already does
- NodeAgentRouter duplicating what TriggerDispatcher already does
- Sidebar composer as a separate subsystem (this is just reading workspace state and rendering markdown)
- Four separate MicroSwarm classes each creating their own kernel (expensive — 4 LLM calls per exchange)
- LinkerSwarm's naive pattern matching (`test_foo` string match) — barely functional

---

## 2. v2 Primitives We Already Have

### 2.1 Actor Model

The `Actor` class already provides everything NodeAgent had:
- Persistent conversation history (`self._history: list[Message]`)
- Sequential inbox processing
- Workspace access
- System prompt building from bundle config
- Event-driven triggering

**Key insight:** We don't need a separate "companion agent" type. Every Actor IS already a companion agent — it just doesn't run post-turn hooks yet.

### 2.2 Event System

v2's event system already has:
- `AgentCompleteEvent` with `agent_id`, `result_summary`, `full_response`
- `AgentMessageEvent` for inter-agent messaging
- `ContentChangedEvent` for file changes
- `CursorFocusEvent` for editor cursor tracking
- Subscription-based routing via `TriggerDispatcher`

Everything needed to trigger companion behavior already exists as events.

### 2.3 Workspace (Cairn + KV)

`AgentWorkspace` already has:
- File read/write/list/delete
- KV store (get/set/delete/list)
- All paths listing

The KV store is particularly relevant — v1 used workspace files for structured data (JSON chat index, links, notes), but v2's KV store is a cleaner fit for structured metadata.

### 2.4 TurnContext API

`TurnContext` already exposes to agent tools:
- `kv_get` / `kv_set` / `kv_delete` / `kv_list` — agents can read/write their own memory
- `send_message` / `broadcast` — inter-agent communication
- `event_emit` — custom event emission
- `graph_get_edges` / `graph_get_children` — graph traversal
- `search_content` — text-based content search

### 2.5 Virtual Agents

`VirtualAgentConfig` lets us define agents in `remora.yaml` that don't correspond to code elements. A "reflector" or "summarizer" virtual agent could subscribe to `AgentCompleteEvent` and process completed turns across the entire system.

### 2.6 Bundle System

Bundles provide:
- `bundle.yaml` with system prompt, model, max_turns, prompts (chat/reactive modes)
- `.pym` tool scripts with access to `TurnContext` capabilities

Post-turn hooks could be defined as bundle config, keeping the configuration declarative.

---

## 3. Design Principle: Post-Turn Hooks, Not Swarms

### 3.1 Why v1's MicroSwarm Approach Was Over-Engineered

v1's approach had several problems:

1. **4 separate LLM calls per exchange.** The summarizer, categorizer, and reflection swarms each created their own kernel and made independent LLM calls. That's 4x the cost and latency for metadata that could be extracted in a single call.

2. **Separate class hierarchy.** MicroSwarm protocol, SwarmContext dataclass, run_post_exchange_swarms orchestrator — all for what amounts to "after a turn completes, do some stuff."

3. **Hardcoded swarm list.** `_SWARMS = [SummarizerSwarm(), CategorizerSwarm(), LinkerSwarm(), ReflectionSwarm()]` — no way to configure which swarms run without code changes.

4. **Parallel execution was premature.** The swarms ran in parallel via `asyncio.gather`, but they all needed the same context and wrote to the same workspace. The LinkerSwarm didn't even use LLM — it was pure string matching.

### 3.2 The Simpler Alternative: Hook Pipeline

Instead of four parallel swarm classes, use a single post-turn hook that:
1. Makes ONE LLM call with a structured output request (JSON) that produces summary, tags, reflection, and links all at once
2. Writes the results to the agent's KV store
3. Optionally emits events for downstream consumers

This is:
- **3x cheaper** (1 LLM call instead of 3-4)
- **Simpler** (one function, not four classes + protocol + orchestrator)
- **Configurable** (enabled/disabled per bundle via bundle.yaml)
- **v2-native** (uses KV store and events, not workspace files)

### 3.3 Hook Definition via Bundle Config

```yaml
# bundle.yaml
post_turn:
  enabled: true
  model: "Qwen/Qwen3-4B"    # can use a smaller/faster model for hooks
  hooks:
    - summarize              # generate one-line summary
    - categorize             # tag with categories
    - reflect                # extract insights
    - link                   # discover cross-node references
```

Bundles that don't want post-turn processing simply omit the `post_turn` key. This keeps it opt-in and declarative.

---

## 4. Design: Post-Turn Hook Pipeline

### 4.1 Hook Protocol

Rather than a complex protocol hierarchy, a single function signature:

```python
# core/hooks.py

@dataclass
class TurnDigest:
    """Results of post-turn analysis — produced by a single LLM call."""
    summary: str           # One-line summary of the exchange
    tags: list[str]        # Category tags (from predefined vocabulary)
    reflection: str        # Insight or observation worth remembering
    links: list[str]       # Node IDs referenced in the exchange

async def digest_turn(
    agent_id: str,
    user_message: str,
    assistant_response: str,
    model_name: str,
    config: Config,
) -> TurnDigest:
    """Single LLM call to extract structured metadata from a completed turn."""
```

This replaces four swarm classes with one function that returns a structured result.

### 4.2 Built-in Hooks

Instead of separate swarm classes, the digest result drives simple KV writes:

```python
async def apply_turn_digest(
    workspace: AgentWorkspace,
    digest: TurnDigest,
    outbox: Outbox,
    agent_id: str,
) -> None:
    """Write digest results to agent's KV store and emit events."""

    # 1. Append to conversation index
    index = await workspace.kv_get("companion/chat_index") or []
    index.append({
        "timestamp": time.time(),
        "summary": digest.summary,
        "tags": digest.tags,
    })
    # Keep only last N entries
    await workspace.kv_set("companion/chat_index", index[-50:])

    # 2. Append reflection to notes (if non-trivial)
    if digest.reflection and digest.reflection != "SKIP":
        notes = await workspace.kv_get("companion/reflections") or []
        notes.append({
            "timestamp": time.time(),
            "insight": digest.reflection,
        })
        await workspace.kv_set("companion/reflections", notes[-30:])

    # 3. Store discovered links
    if digest.links:
        links = await workspace.kv_get("companion/links") or []
        existing = {link["target"] for link in links}
        for target in digest.links:
            if target not in existing:
                links.append({"target": target, "timestamp": time.time()})
        await workspace.kv_set("companion/links", links)

    # 4. Emit event for downstream consumers (web UI, sidebar, etc.)
    await outbox.emit(TurnDigestedEvent(
        agent_id=agent_id,
        summary=digest.summary,
        tags=tuple(digest.tags),
    ))
```

### 4.3 Integration Point in Actor

The hook runs after `_complete_agent_turn()` in `Actor._execute_turn()`. It's a fire-and-forget background task (same as v1's `asyncio.create_task(self._run_swarms(ctx))`), so it doesn't block the main processing loop:

```python
# In Actor._execute_turn(), after _complete_agent_turn():

if self._should_run_post_turn(bundle_config):
    asyncio.create_task(
        self._run_post_turn_hooks(
            bundle_config=bundle_config,
            user_message=messages[1].content,
            response_text=response_text,
            workspace=workspace,
            outbox=outbox,
        )
    )
```

The `_should_run_post_turn()` check reads `post_turn.enabled` from bundle config. The actual hook execution is a private method on Actor that calls `digest_turn()` then `apply_turn_digest()`.

### 4.4 Configuration

**Bundle-level** (in `bundle.yaml`):
```yaml
post_turn:
  enabled: true
  model: "Qwen/Qwen3-1.7B"   # smaller model for metadata extraction
  max_summary_length: 120
  tag_vocabulary:
    - bug
    - question
    - refactor
    - explanation
    - test
    - performance
    - design
    - insight
    - todo
```

**Global defaults** (in `remora.yaml`):
```yaml
post_turn:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
```

Bundle config overrides global. If neither specifies `post_turn`, hooks don't run.

---

## 5. Design: Agent Memory via Workspace KV

### 5.1 Conversation Indexing

KV key: `companion/chat_index`

Value: List of dicts, each with:
```json
{
  "timestamp": 1710000000.0,
  "summary": "Discussed edge case in error handling for null inputs",
  "tags": ["bug", "edge_case"]
}
```

Capped at 50 entries. Oldest entries are evicted on append.

### 5.2 Agent Notes / Reflections

KV key: `companion/reflections`

Value: List of dicts:
```json
{
  "timestamp": 1710000000.0,
  "insight": "This function silently swallows FileNotFoundError — potential data loss risk"
}
```

Capped at 30 entries. These are the agent's accumulated knowledge about its code element.

### 5.3 Tags and Categories

Tags are stored per-entry in the chat index (section 5.1). No separate storage needed — the tag vocabulary is defined in bundle config and the single digest LLM call produces tags alongside the summary.

### 5.4 Cross-Agent Links

KV key: `companion/links`

Value: List of dicts:
```json
{
  "target": "test_calculate_total",
  "timestamp": 1710000000.0
}
```

These represent relationships discovered during conversation. The LLM is prompted with the list of known node IDs (from graph) and asked which ones are referenced in the exchange.

**Key improvement over v1:** v1's LinkerSwarm did naive string matching. v2's approach uses the LLM (which already has the exchange context) to identify references more accurately, as part of the same digest call.

### 5.5 Memory in System Prompt

The Actor's `_build_system_prompt()` already reads bundle config. We extend it to also read companion KV data and inject it into the system prompt:

```python
# In Actor._build_system_prompt() or a new helper:

async def _build_companion_context(self, workspace: AgentWorkspace) -> str:
    """Build companion memory context for system prompt injection."""
    sections = []

    # Recent reflections
    reflections = await workspace.kv_get("companion/reflections") or []
    if reflections:
        recent = reflections[-5:]  # Last 5 insights
        lines = [f"- {r['insight']}" for r in recent]
        sections.append("## My Observations\n" + "\n".join(lines))

    # Recent conversation summaries
    index = await workspace.kv_get("companion/chat_index") or []
    if index:
        recent = index[-3:]  # Last 3 conversations
        lines = [f"- {entry['summary']}" for entry in recent]
        sections.append("## Recent Conversations\n" + "\n".join(lines))

    # Known links
    links = await workspace.kv_get("companion/links") or []
    if links:
        lines = [f"- {link['target']}" for link in links[:8]]
        sections.append("## Related Nodes\n" + "\n".join(lines))

    return "\n\n".join(sections) if sections else ""
```

This replaces v1's approach of building the system prompt from workspace files. KV reads are faster than file reads and the data is already structured.

---

## 6. Design: Sidebar / Summary Composition

### 6.1 What "Sidebar" Means in v2

In v1, "sidebar" meant a Neovim split panel showing composed markdown. In v2, the primary UI surface is the web panel. The "sidebar" equivalent is the agent detail view in the web UI — when you click on a node, you see its status, conversations, and accumulated knowledge.

This means sidebar composition isn't a separate system — it's the web API returning structured data that the frontend renders.

### 6.2 Composition as a Web API Endpoint

Rather than a sidebar composer class, add a web API endpoint that reads the agent's companion KV data:

```
GET /api/nodes/{node_id}/companion
```

Response:
```json
{
  "reflections": [...],
  "chat_index": [...],
  "links": [...],
  "status": "idle",
  "last_active": 1710000000.0
}
```

The web frontend renders this data in whatever layout makes sense. No markdown composition needed — the frontend has full control over presentation.

### 6.3 Web API Integration

This is a simple addition to `web/server.py`:

```python
@app.route("/api/nodes/{node_id}/companion", methods=["GET"])
async def get_companion_data(request):
    node_id = request.path_params["node_id"]
    workspace = await services.workspace_service.get_agent_workspace(node_id)
    return JSONResponse({
        "reflections": await workspace.kv_get("companion/reflections") or [],
        "chat_index": await workspace.kv_get("companion/chat_index") or [],
        "links": await workspace.kv_get("companion/links") or [],
    })
```

For LSP integration, the same data can be returned via the `remora.chat` command or as hover content enrichment.

---

## 7. Concrete Implementation Plan

### 7.1 Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `core/hooks.py` | `TurnDigest`, `digest_turn()`, `apply_turn_digest()` | ~120 |

That's it. One file.

### 7.2 Files to Modify

| File | Change | ~Delta |
|------|--------|--------|
| `core/actor.py` | Add `_run_post_turn_hooks()`, `_should_run_post_turn()`, `_build_companion_context()`. Call hooks after `_complete_agent_turn()`. Inject companion context into system prompt. | +80 lines |
| `core/events/types.py` | Add `TurnDigestedEvent` | +10 lines |
| `web/server.py` | Add `/api/nodes/{node_id}/companion` endpoint | +15 lines |
| `web/static/index.html` | Render companion data in node detail panel | +30 lines |

**Total new code: ~255 lines.**

Compare to v1's companion system: ~1,200 lines across 15+ files.

### 7.3 Configuration Changes

Add to `Config`:
```python
# Global post-turn defaults
post_turn_enabled: bool = False
post_turn_model: str = ""  # defaults to model_default if empty
```

Bundle-level config already supports arbitrary keys in `bundle.yaml`, so `post_turn:` section needs no schema changes.

### 7.4 Event Types to Add

```python
class TurnDigestedEvent(Event):
    """Post-turn analysis completed for an agent."""
    agent_id: str
    summary: str = ""
    tags: tuple[str, ...] = ()
```

One event. Consumers (web SSE, virtual agents) can subscribe to this for real-time updates.

---

## 8. Alternative Approaches Considered

### A. Port v1's Companion as a Separate Module

**Rejected.** This would create a parallel agent system alongside Actor, exactly what v2 was designed to eliminate. The whole point of v2's architecture is that Actor IS the agent — adding a separate NodeAgent/CompanionAgent concept goes against the grain.

### B. Implement Swarms as Grail Tool Scripts

**Partially adopted.** The idea of implementing post-turn processing via `.pym` scripts has appeal (fully configurable, no code changes needed). However:
- Grail tools are designed to be called BY the agent during its turn, not after
- Running tools after the turn would require a separate execution context
- The overhead of loading and executing 4 separate scripts is worse than one function call

The compromise: `digest_turn()` is a core function, but the tag vocabulary and enablement are bundle-configurable.

### C. Use Virtual Agents for All Companion Functionality

**Considered but too indirect.** A virtual agent subscribing to `AgentCompleteEvent` could do summarization/categorization, but:
- It would need to read the originating agent's workspace to write KV data
- Cross-workspace access violates the sandboxing model
- The latency of routing through events → dispatcher → new actor → LLM turn is much higher than an inline hook

Virtual agents ARE useful for cross-agent aggregation (e.g., a "project overview" agent), but per-agent memory management should be inline in the actor.

### D. Single LLM Call vs. Multiple Specialized Calls

**Chosen: Single call.** Modern LLMs handle structured output well. One call that returns `{"summary": "...", "tags": [...], "reflection": "...", "links": [...]}` is:
- 3x cheaper than 3 separate calls
- Faster (one round trip instead of three)
- Simpler to implement and maintain
- Equally accurate for these simple extraction tasks

The only downside is that a single call failure loses all metadata. But since this is fire-and-forget background processing, occasional failures are acceptable — the agent's core turn already completed successfully.

---

## Appendix: Alternative Integration Approaches

The main body of this document recommends a specific design (inline post-turn hooks in Actor with single-LLM-call digest). This appendix explores all other viable approaches in depth, evaluating each as a genuine option rather than a straw man.

---

### Approach A: Event-Driven Observer Pattern (Virtual Agent as Companion Orchestrator)

**How it works:** Define a virtual agent (e.g., `companion-observer`) in `remora.yaml` that subscribes to `AgentCompleteEvent`. When any actor finishes a turn, the event routes to this virtual agent, which runs its own LLM turn to digest the completed exchange. It reads the originating agent's full_response from the event payload, produces summary/tags/reflection/links, and writes the results back to the originating agent's workspace KV store.

```yaml
virtual_agents:
  - id: companion-observer
    role: companion
    subscriptions:
      - event_types: ["AgentCompleteEvent"]
```

**Pros:**
- Zero changes to Actor — fully decoupled. The companion logic lives entirely outside the core execution path.
- Leverages existing virtual agent infrastructure; no new concepts introduced.
- The observer can evolve independently — swap in a more sophisticated analysis agent without touching actor.py.
- Naturally handles cross-agent aggregation: the observer sees ALL agent completions and could build project-wide summaries, detect patterns across agents, etc.
- Testable in isolation — just a bundle with a system prompt and tools.

**Cons:**
- **Cross-workspace access problem.** The observer agent lives in its own Cairn workspace but needs to write KV data into the *originating* agent's workspace. This requires either: (a) adding a `write_to_foreign_workspace(node_id, key, value)` capability to TurnContext, which breaks the sandboxing model; or (b) having the observer emit a new event (e.g., `CompanionDigestEvent`) that the originating actor picks up and self-applies, which adds a second event hop and more latency.
- **Latency.** The event routing path is: AgentCompleteEvent → EventStore → TriggerDispatcher → companion-observer inbox → Actor._execute_turn() → LLM call → result. This is a full actor turn cycle with its own semaphore wait, kernel creation, etc. — potentially seconds of delay vs. milliseconds for an inline hook.
- **Resource contention.** The observer consumes a concurrency slot from the semaphore, potentially delaying real agent work.
- **Event payload limitations.** `AgentCompleteEvent.full_response` carries the assistant's response, but the user message (trigger content) isn't on the event. The observer would need to reconstruct context from the event store history.

**Implications:**
- Would need `AgentCompleteEvent` enriched with user_message content (or the observer queries event history).
- Either breaks workspace sandboxing or requires a two-hop event pattern.
- Best suited if we want companion logic to be *community-configurable* (just write a different bundle), at the cost of integration tightness.

**Opportunities:**
- The cross-agent view is genuinely powerful. An observer that sees all completions could build a "project health dashboard" — which agents are most active, what categories of work dominate, where bugs cluster.
- Could evolve into a meta-learning system: the observer notices patterns ("this agent keeps hitting the same error") and proactively adjusts system prompts or routes messages.

---

### Approach B: Grail Post-Turn Scripts (Bundle-Defined `.pym` Hooks)

**How it works:** Extend the Grail tool system to support a new script lifecycle phase: `post_turn`. After an actor completes its LLM turn, it scans the workspace for `_bundle/post_turn/*.pym` scripts and executes them sequentially, passing the turn context (user message, assistant response, workspace, outbox).

```
bundles/code-agent/
├── bundle.yaml
├── tools/
│   ├── read_source.pym
│   └── write_file.pym
└── post_turn/
    ├── 01_summarize.pym
    ├── 02_categorize.pym
    └── 03_reflect.pym
```

Each `.pym` script has access to a `post_turn_ctx` object with the exchange content and workspace KV methods.

**Pros:**
- **Fully bundle-configurable.** Different bundles can have completely different post-turn behavior. A test-agent bundle might have a hook that checks if tests still pass; a code-agent might have summarize/reflect; a review-agent might have none.
- **No core code changes for new hooks.** Adding a new post-turn behavior is just adding a `.pym` file to a bundle directory.
- **Familiar pattern.** Grail scripts are already how agents get tools; extending the concept to post-turn processing is conceptually consistent.
- **Gradual adoption.** Bundles opt in by including post_turn scripts. No global config needed.

**Cons:**
- **No LLM access from scripts.** Grail scripts execute Python code with access to TurnContext capabilities, but they can't create kernels or make LLM calls. The summarizer, categorizer, and reflection hooks all need LLM calls. We'd either need to: (a) add `llm_call()` to the TurnContext API surface (significant new capability with security implications), or (b) accept that post-turn scripts can only do non-LLM processing (string manipulation, KV writes, event emission).
- **Execution overhead.** Loading and executing multiple `.pym` scripts (each with Grail's parsing, sandboxing, and capability injection) per turn adds non-trivial overhead compared to a single function call.
- **Ordering and dependencies.** Scripts run sequentially in filename order, but there's no way to express dependencies between them (e.g., "categorizer needs the summary first").
- **Error isolation is tricky.** If script 02 fails, should 03 still run? The existing Grail execution model doesn't handle multi-script pipelines.

**Implications:**
- Requires either extending Grail with LLM call capability or accepting non-LLM-only hooks.
- Requires a new Grail execution context (`PostTurnContext` vs. `TurnContext`) to provide the exchange content.
- The `.pym` discovery and execution loop adds ~50-80 lines to actor.py plus changes to grail.py.

**Opportunities:**
- If we add `llm_call()` to the tool API, it unlocks a LOT more than just post-turn hooks. Agents could have tools that call other LLMs, do chain-of-thought sub-reasoning, etc. This is a much bigger architectural decision with wide implications.
- The sequential script pipeline pattern could be reused for pre-turn hooks (context enrichment before the LLM call) or on-error hooks.

---

### Approach C: Actor Middleware / Decorator Chain

**How it works:** Introduce a middleware pattern where Actor's `_execute_turn()` is wrapped by a chain of decorators/middleware that can intercept before and after the turn. The companion functionality is implemented as a middleware that runs after the core turn.

```python
class PostTurnMiddleware:
    """Middleware that runs companion analysis after each actor turn."""

    async def after_turn(
        self, actor: Actor, trigger: Trigger, workspace: AgentWorkspace,
        user_message: str, response_text: str, outbox: Outbox,
    ) -> None:
        digest = await digest_turn(...)
        await apply_turn_digest(workspace, digest, outbox, actor.node_id)

class Actor:
    def __init__(self, ..., middleware: list[ActorMiddleware] | None = None):
        self._middleware = middleware or []

    async def _execute_turn(self, trigger, outbox):
        # ... existing turn logic ...
        for mw in self._middleware:
            await mw.after_turn(self, trigger, workspace, user_msg, response, outbox)
```

**Pros:**
- **Clean separation of concerns.** Core actor logic stays untouched; companion behavior is a pluggable layer.
- **Composable.** Multiple middleware can be stacked: companion, telemetry, rate limiting, etc.
- **Testable.** Middleware can be tested independently of Actor.
- **Extensible.** Third parties (or future us) can add new actor behaviors without modifying actor.py.

**Cons:**
- **Over-engineering for one use case.** Right now we have exactly ONE post-turn behavior we want to add. A full middleware system is a lot of abstraction for one hook.
- **Ordering complexity.** Middleware ordering matters and is non-obvious. Who decides the order? Config? Registration order?
- **API surface creep.** The middleware needs access to actor internals (workspace, outbox, trigger, user message, response text). Defining a clean interface that provides enough context without leaking actor implementation details is tricky.
- **Lifecycle management.** When are middleware instantiated? Per-actor? Per-pool? Who injects them?

**Implications:**
- Adds a new abstraction (`ActorMiddleware` protocol, before/after hooks) to a codebase that prides itself on minimal abstractions.
- The middleware chain needs to be wired through ActorPool → Actor constructor, adding ceremony to actor creation.
- If we ever want pre-turn middleware (context enrichment), the same pattern works — but YAGNI says don't build for that now.

**Opportunities:**
- If remora evolves to need more cross-cutting concerns (observability, auditing, rate limiting per agent, A/B testing different prompts), middleware becomes very valuable.
- Could be the foundation for a plugin system if remora ever needs one.

---

### Approach D: Event Sourcing — Derive Memory from Event History

**How it works:** Instead of producing companion metadata at turn time, derive it lazily from the event history. When someone asks "what are this agent's reflections?" or "what tags apply?", query the EventStore for that agent's history and compute the answer on the fly (or cache it).

```python
async def get_agent_reflections(agent_id: str, event_store: EventStore) -> list[str]:
    """Derive reflections by replaying agent's event history."""
    events = await event_store.get_events_for_agent(agent_id, limit=100)
    complete_events = [e for e in events if e["event_type"] == "AgentCompleteEvent"]
    # LLM call to summarize the entire history into key reflections
    ...
```

**Pros:**
- **No post-turn processing at all.** Zero overhead on the hot path. No background tasks, no extra LLM calls during normal operation.
- **Always fresh.** Derived data can't go stale because it's computed from the source of truth (events).
- **Retroactive.** Can produce companion data for turns that happened before companion was enabled.
- **Simpler Actor.** No hooks, no middleware, no additional code in the turn pipeline.

**Cons:**
- **Expensive on read.** Every time someone views an agent's companion data, we potentially need to: query event history, aggregate, possibly make LLM calls. This shifts cost from write time to read time — and reads may happen more often (every cursor focus, every web panel view).
- **Caching complexity.** To avoid re-deriving on every read, we need a caching layer with invalidation on new events. This is the same problem we're trying to solve, just with more indirection.
- **No incremental insights.** The post-turn digest model produces insights in the context of a single exchange. The event sourcing model would need to analyze the entire history to produce equivalent insights, which is harder and more expensive.
- **LLM cost shifts, doesn't disappear.** Instead of a cheap per-turn LLM call (small context), we get an expensive on-demand LLM call (large context — entire agent history).

**Implications:**
- Works best with a materialized view pattern: derive on first request, cache, invalidate on new events. But this IS essentially the post-turn hook approach with extra steps.
- Better suited for one-off analytics ("show me a summary of this agent's entire history") than for ongoing incremental metadata.

**Opportunities:**
- Could be a complement to, rather than replacement for, per-turn digests. The KV store holds incremental per-turn digests (from hooks), and a separate "full history analysis" endpoint provides deeper retrospective analysis on demand.
- The event store already has all the data. A "project retrospective" feature that analyzes all agent activity could be built entirely on event replay without any new storage.

---

### Approach E: LLM-Free Heuristic Companion (No Additional LLM Calls)

**How it works:** Skip the LLM calls entirely for post-turn metadata. Instead, use fast heuristics:
- **Summary:** First 120 chars of the assistant response (or the user message if response is code-heavy).
- **Tags:** Keyword matching against a vocabulary (`if "test" in text → "test"`, `if "bug" in text → "bug"`, etc.).
- **Links:** Regex/AST matching for node name references in the exchange text (improved version of v1's LinkerSwarm).
- **Reflection:** Skip entirely, or use TF-IDF to extract the most distinctive sentence.

```python
def heuristic_digest(user_message: str, response_text: str, known_nodes: list[str]) -> TurnDigest:
    combined = f"{user_message}\n{response_text}"
    return TurnDigest(
        summary=response_text[:120].split("\n")[0],
        tags=_keyword_tags(combined),
        reflection="",  # or TF-IDF extraction
        links=_find_node_references(combined, known_nodes),
    )
```

**Pros:**
- **Zero LLM cost.** No additional model calls, no latency, no GPU dependency for companion features.
- **Instant.** Runs in microseconds, not seconds. No background task needed — can run synchronously in the turn pipeline.
- **Always available.** Doesn't depend on model configuration, API keys, or server availability.
- **Deterministic.** Same input always produces the same output. No LLM non-determinism.

**Cons:**
- **Low quality summaries.** First-120-chars is often code or boilerplate, not a meaningful summary.
- **Crude categorization.** Keyword matching produces false positives ("I tested this" → "test" tag even when discussing manual testing, not automated tests) and misses nuance.
- **No reflection.** The most valuable companion feature (extracting insights) requires understanding, not pattern matching.
- **Brittle link detection.** Regex matching for node names in natural language text produces noise (common names like `get`, `set`, `run` match everywhere).

**Implications:**
- Could serve as a fast default with LLM-based digests as an opt-in upgrade. Two tiers: heuristic (always on, free) and LLM-enhanced (opt-in, costs a model call).
- The heuristic approach is still valuable for the summary-and-tags use case where approximate is good enough.

**Opportunities:**
- **Tiered approach is compelling.** Always run heuristics (free, instant), optionally run LLM digest (configurable, async). This gives every agent basic companion memory at zero cost, with richer memory for agents where it's configured.
- The heuristic tags could feed into the LLM digest prompt as "initial tags" that the LLM refines, getting better results from the LLM call for free.

---

### Approach F: Dedicated Companion Actor Per Agent (Actor Composition)

**How it works:** For each code agent, automatically create a paired "shadow" actor whose sole job is companion processing. The shadow subscribes to the primary actor's `AgentCompleteEvent`, runs the digest, and writes to a shared workspace or the primary's KV store.

```
code_agent:src.auth.login       ← primary actor (runs code analysis)
companion:src.auth.login         ← shadow actor (runs post-turn digests)
```

The shadow uses a lightweight bundle (small model, simple prompt) optimized for metadata extraction.

**Pros:**
- **Clean separation.** The primary actor is completely unaware of companion processing. No hooks, no middleware, no changes to actor.py.
- **Independent lifecycle.** Shadow actors can be evicted, restarted, or reconfigured independently.
- **Different model.** The shadow can use a tiny model (Qwen3-0.6B) while the primary uses a larger model. Bundle-level model selection already supports this.
- **Parallel execution.** Shadow and primary run on different concurrency slots, so companion work never blocks primary work.

**Cons:**
- **2x actor count.** Every code node now has two actors, doubling memory usage and ActorPool management overhead.
- **Workspace isolation problem.** Same as Approach A — the shadow needs write access to the primary's KV store.
- **Configuration complexity.** Need rules for "which agents get shadows?" — another config surface to maintain.
- **Tight event coupling.** If the primary agent's event format changes, all shadows break.
- **Naming/ID scheme.** Need a convention for shadow IDs that's predictable and doesn't collide with real nodes.

**Implications:**
- Requires either shared workspace access or a KV proxy mechanism.
- ActorPool needs awareness of shadow actors (don't evict them independently of their primary).
- Doubles the node count in the graph, which affects the web UI, LSP, and any graph queries.

**Opportunities:**
- The "shadow actor" pattern could extend beyond companion — e.g., a test-runner shadow that automatically runs tests after a code agent modifies code, or a reviewer shadow that reviews changes.
- If we ever want per-agent plugins/extensions, the shadow pattern provides a clean hook point.

---

### Approach G: Workspace File Conventions (v1-Style, Modernized)

**How it works:** Instead of KV store, use structured workspace files as v1 did, but with a cleaner convention. Each agent's workspace has a `_companion/` directory with well-defined JSON files:

```
_companion/
├── index.json        # Chat summaries and tags
├── reflections.json  # Accumulated insights
├── links.json        # Cross-agent references
└── profile.json      # Agent personality/preferences over time
```

Post-turn hooks write to these files. The system prompt builder reads them.

**Pros:**
- **Human-inspectable.** Workspace files can be viewed directly on disk (in `.remora/agents/<id>/`). KV store contents require tooling to inspect.
- **Git-trackable.** If someone wanted to version-control agent knowledge, files are easier than KV blobs.
- **Familiar pattern.** v1 users would recognize the approach.
- **No new API.** Uses existing `workspace.read()` / `workspace.write()` — no new KV methods needed.

**Cons:**
- **Slower I/O.** File read/write through Cairn is slower than KV get/set, especially for small structured data.
- **Parse overhead.** Every read requires JSON parse, every write requires JSON serialize + write. KV store handles serialization internally.
- **Concurrent access risk.** If a post-turn hook is writing `index.json` while the system prompt builder is reading it, we can get partial reads. KV operations are atomic.
- **Path convention maintenance.** Need to document and enforce the `_companion/` directory structure. KV key prefixes are simpler.

**Implications:**
- Workspace file approach is essentially "KV store but worse" for structured data. The v2 KV store exists precisely to avoid the problems v1 had with structured data in files.
- Could be useful for *human-authored* notes (a `_companion/user_notes.md` that the developer writes), but not for machine-generated structured data.

**Opportunities:**
- Hybrid approach: KV store for machine-generated structured data, workspace files for human-readable artifacts (rendered markdown summaries, exportable reports).
- A `_companion/summary.md` file that's regenerated after each digest could provide a nice human-readable view without requiring the web UI.

---

### Summary Comparison Matrix

| Approach | New Core Code | LLM Cost | Latency | Complexity | Cross-Agent? | Configurable? |
|----------|:------------:|:---------:|:-------:|:----------:|:------------:|:-------------:|
| **Recommended (inline hooks)** | ~255 lines | 1 call/turn | Low | Low | No | Via bundle |
| **A. Virtual Agent Observer** | ~50 lines | 1 call/turn | High | Medium | Yes | Via config |
| **B. Grail Post-Turn Scripts** | ~130 lines | 0-N calls | Medium | Medium | No | Via bundle |
| **C. Actor Middleware** | ~200 lines | 1 call/turn | Low | High | No | Via code |
| **D. Event Sourcing** | ~100 lines | On-demand | Variable | Medium | Yes | N/A |
| **E. Heuristic (no LLM)** | ~80 lines | 0 | Instant | Low | No | Via bundle |
| **F. Shadow Actors** | ~150 lines | 1 call/turn | Medium | High | Sort of | Via config |
| **G. Workspace Files** | ~200 lines | 1 call/turn | Low | Low | No | Via bundle |

**Recommended hybrid:** The main document's approach (inline hooks with single LLM call) as the primary mechanism, with Approach E (heuristic) as a zero-cost fallback when `post_turn.model` is not configured. This gives every agent basic companion memory for free, with LLM-enhanced digests for agents where a model is available.
