# Codebase Navigation Guide

This section provides guidance on where to start studying the remora-v2 codebase and how to trace through key scenarios to understand how the library works.

## Recommended Learning Path

For the most effective understanding of remora-v2, I recommend studying the codebase in this sequence:

1. **Core Concepts and Data Models** → Understand what represents code and agents
2. **Event System** → Learn how components communicate  
3. **Persistence Layer** → See how state is stored durably
4. **Discovery and Reconciliation** → Understand how the system stays in sync with the filesystem
5. **Agent Execution Model** → See how agents actually work and process events
6. **Interfaces** → See how users and external systems interact with the system

This follows the natural flow: discover → store → event → act → interface.

## Important Entry Points and Starting Points

Here are the most important files to study, organized by topic and recommended order:

### 1. Start Here: Core Data Models
**File**: `src/remora/core/node.py`
**Why start here**: This defines the fundamental building blocks of the system - what represents code elements and agents.
**What to look for**:
- `CodeElement`: Immutable representation of discovered code
- `Agent`: Runtime state of an autonomous agent
- `CodeNode`: Combined view (historical compatibility - note we don't need to maintain this going forward)
- The conversion methods (`to_element()`, `to_agent()`, `to_row()`, `from_row()`) show how data moves between layers

**Study Exercise**: Trace how a `CodeElement` becomes an `Agent` and vice versa. Notice what data is shared vs. what's specific to each.

### 2. Understand Communication: Event System
**Files**: `src/remora/core/events/` (study in this order)
1. `types.py` - All event definitions
2. `bus.py` - In-memory publish/subscribe (simpler to understand first)
3. `store.py` - Persistent storage with real-time distribution
4. `dispatcher.py` - Routing events to agents
5. `subscriptions.py` - Subscription matching logic

**What to look for**:
- How the base `Event` class automatically sets `event_type`
- How specific events add relevant fields (e.g., `AgentStartEvent` has `agent_id` and `node_name`)
- The separation between `EventBus` (real-time) and `EventStore` (persistent)
- How events flow: creation → persistence → broadcasting → dispatcher → agent inboxes

**Study Exercise**: Trace the lifecycle of a `NodeDiscoveredEvent` from creation in the reconciler to handling in an agent. Follow it through all the event system components.

### 3. See How State Persists: Storage Layer
**File**: `src/remora/core/graph.py`
**Why study this**: This shows how the system durably stores its state.
**What to look for**:
- `NodeStore`: Storage for code elements (the `nodes` table)
- `AgentStore`: Storage for agent runtime status (the `agents` table) 
- How the table schemas match the data models
- The `upsert_*`, `get_*`, `list_*`, `delete_*`, and `transition_status*` methods
- How edges (relationships between nodes) are stored
- Indexes that make queries efficient

**Study Exercise**: Follow how a `CodeNode` gets saved to and retrieved from the database. Notice the conversion between model objects and database rows.

### 4. Understand How the System Stays Current: Discovery & Reconciliation
**Files**: `src/remora/code/` (study in this order)
1. `discovery.py` - Core tree-sitter based parsing
2. `reconciler.py` - Main loop that detects changes and updates the system
3. `projections.py` - Converts raw discoveries to persistent nodes
4. `paths.py` - Path resolution utilities

**What to look for**:
- How `discover()` uses tree-sitter to parse files and extract code elements
- How `_parse_file()` processes syntax tree matches into `CSTNode` objects
- How `_build_name_from_tree()` constructs hierarchical names by walking syntax tree parents
- How the reconciler tracks file state (`_file_state`) to detect changes
- How additions, modifications, and deletions are detected and turned into events
- How `project_nodes()` bridges discovery to persistence

**Study Exercise**: Trace what happens when a file is modified: from filesystem detection → tree-sitter parsing → change detection → event generation. Follow the data through all these components.

### 5. See How Agents Work: Execution Model
**Files**: `src/remora/core/` (study in this order)
1. `actor.py` - The `AgentActor` that processes events one at a time
2. `runner.py` - Manages agents and routes events to them
3. `externals.py` - The API available to agent tool scripts
4. `kernel.py` - Interface to LLM providers
5. `workspace.py` - Manages isolated agent workspaces

**What to look for**:
- How `AgentActor` uses an `asyncio.Queue` for its inbox
- The `_run()` loop that processes events sequentially
- How `_should_trigger()` implements cooldown and depth policies
- How `_execute_turn()` carries out the actual agent work:
  - Getting the current node
  - Transitioning statuses
  - Emitting start events
  - Setting up workspace and context
  - Discovering tools
  - Building prompts
  - Running the LLM kernel
  - Handling results and cleaning up
- How `AgentRunner` manages the lifecycle of all agents
- How the `Outbox` pattern works for event emission

**Study Exercise**: Trace what happens when an agent receives a `NodeChangedEvent`: from inbox → processing → LLM interaction → result emission → status reset. Notice how the agent's isolated workspace is used.

### 6. See How Users Interact: Interfaces
**Files**: (study based on your interest)
1. `src/remora/__main__.py` - CLI entry point (`remora start`, `remora discover`)
2. `src/remora/web/server.py` - Web interface with REST APIs and SSE streaming
3. `src/remora/lsp/server.py` - Language Server Protocol adapter (if interested in editor integration)

**What to look for**:
- How the CLI parses arguments and starts the system
- How the web server exposes graph data, events, and interaction endpoints
- How Server-Sent Events work for real-time updates
- How the LSP adapter integrates with editors (if relevant to you)

**Study Exercise**: Trace what happens when a user opens the web dashboard: from HTTP request → data retrieval from stores → HTML/JS delivery → SSE connection → real-time event display.

## Tracing Key Scenarios

To really understand how the system works, try tracing these complete scenarios:

### Scenario 1: File Change → Discovery → Event → Agent Processing
**Start**: Developer saves changes to a Python file
**End**: Agent processes the change and emits a result

**Path to Follow**:
1. Filesystem change detected by `watchfiles` in `reconciler.py:_run_watching()`
2. `reconciler.py:_reconcile_file()` calls `discover()`
3. `discovery.py:discover()` uses tree-sitter to parse the file
4. `discovery.py:_parse_file()` extracts `CSTNode` objects
5. `reconciler.py` compares new/old state and detects modification
6. `projections.py:project_nodes()` converts to `CodeNode` and updates storage
7. `reconciler.py` publishes `NodeChangedEvent` via `EventStore.append()`
8. `event_store.py:append()` persists event and fans out to `EventBus` and `TriggerDispatcher`
9. `dispatcher.py:dispatch()` finds matching agents via `SubscriptionRegistry`
10. `runner.py:_route_to_actor()` puts event in agent's inbox
11. `actor.py:AgentActor._run()` pulls event from inbox
12. `actor.py:AgentActor._execute_turn()` processes the event:
    - Gets current `CodeNode` from `NodeStore`
    - Transitions statuses to `RUNNING`
    - Emits `AgentStartEvent`
    - Sets up workspace and loads bundle
    - Discovers tools and builds prompt
    - Runs LLM kernel
    - Emits `AgentCompleteEvent` or `AgentErrorEvent`
    - Resets statuses to `IDLE`
13. All events are persisted and made available via web interface/SSE

### Scenario 2: User Interaction via Web Interface
**Start**: User clicks a button in the web dashboard to send a message to an agent
**End**: Agent receives and processes the message

**Path to Follow**:
1. Browser sends POST request to `/api/chat` with `{"node_id": "...", "message": "..."}`
2. `web/server.py:api_chat()` validates input and calls `event_store.append()`
3. `event_store.py:append()` persists `HumanChatEvent` and fans it out
4. `dispatcher.py:dispatch()` finds agents subscribed to `HumanChatEvent` (typically all agents via wildcard subscription)
5. Agents receive event in their inboxes and process it like any other event
6. Agent might respond by emitting an `AgentMessageEvent` or `AgentTextResponse`
7. Response events are persisted and made available via `/api/events` and `/sse`

### Scenario 3: Agent-to-Agent Communication
**Start**: One agent decides to send a message to another agent
**End**: Target agent receives and processes the message

**Path to Follow**:
1. Source agent, during `_execute_turn()`, decides to send a message
2. Source agent creates `AgentMessageEvent(from_agent="source", to_agent="target", content="...")`
3. Source agent emits event via its `outbox` (which tags it and writes to `EventStore`)
4. `event_store.py:append()` persists event and fans it out
5. `dispatcher.py:dispatch()` finds the target agent via subscription (agents typically subscribe to `to_agent=their_id`)
6. Target agent receives event in inbox and processes it
7. Target agent might respond with another message or take some action
8. All events flow through the same persistence and distribution system

## How to Explore Effectively

Here are some practical tips for navigating and understanding the codebase:

### Use Your IDE's Navigation Features
- **Go to Definition**: Jump from usage to implementation (e.g., click on `EventStore` to see its definition)
- **Find References**: See where a class or method is used throughout the codebase
- **Call Hierarchy**: See who calls a method and who that method calls
- **Type Hierarchy**: See inheritance relationships (especially useful for the event system)

### Look for Patterns
Remora v2 uses several recurring patterns:
- **Builder/Factory patterns**: Look for functions that create complex objects
- **Strategy pattern**: Different language plugins for discovery
- **Decorator pattern**: The `Outbox` adds metadata to events
- **Observer pattern**: The event system itself is an observer pattern implementation
- **Template method**: The `_execute_turn` in `AgentActor` follows a fixed sequence with customizable parts

### Follow the Data
When trying to understand a component, ask:
- What data comes in?
- What transformations happen to it?
- What data goes out?
- Where does it go next?

This works particularly well for tracing:
- Code elements: `CSTNode` → `CodeNode` → storage → retrieval → agent use
- Events: creation → persistence → distribution → handling → new events
- Configuration: files → `Config` object → service initialization → component use

### Use the Tests as Documentation
The test files (`tests/unit/`) often show:
- How to instantiate and use components
- What the expected behavior is
- Edge cases and error conditions
- Proper ways to mock dependencies

### Start Small, Then Expand
When exploring:
1. Start with a single function or method
2. Understand what it does in isolation
3. See how it's called
4. See what it calls
5. Gradually build up your understanding of the larger system

### Don't Get Bogged Down in Details
On your first pass through a file:
- Focus on the "what" and "why" rather than the "how" of every line
- Come back later to examine complex algorithms or optimizations
- Use comments and docstrings as your guide to the author's intent

## Quick Reference: File Purposes

Here's a quick reference to help you find what you're looking for:

### Core Concepts
- `src/remora/core/node.py` - Code elements, agents, and their relationships
- `src/remora/core/types.py` - Shared enums, statuses, and basic types

### Event System
- `src/remora/core/events/types.py` - All event definitions
- `src/remora/core/events/bus.py` - In-memory publish/subscribe
- `src/remora/core/events/store.py` - Persistent event storage
- `src/remora/core/events/dispatcher.py` - Routing persistent events to agents
- `src/remora/core/events/subscriptions.py` - Subscription matching logic

### Persistence
- `src/remora/core/graph.py` - Storage for code elements and agents
- `src/remora/core/db.py` - Database connection wrapper

### Discovery & Reconciliation
- `src/remora/code/discovery.py` - Tree-sitter based parsing
- `src/remora/code/reconciler.py` - Main reconciliation loop
- `src/remora/code/projections.py` - Converting discoveries to persistent nodes
- `src/remora/code/paths.py` - Path resolution utilities

### Agent Execution
- `src/remora/core/actor.py` - Agent processing loop and outbox
- `src/remora/core/runner.py` - Agent lifecycle management
- `src/remora/core/externals.py` - API available to agent tools
- `src/remora/core/kernel.py` - LLM provider interface
- `src/remora/core/workspace.py` - Workspace management

### Interfaces
- `src/remora/__main__.py` - CLI entry point
- `src/remora/web/server.py` - Web interface (APIs and SSE)
- `src/remora/lsp/server.py` - Language Server Protocol adapter

### Configuration
- `src/remora/core/config.py` - Configuration loading and validation

## Final Tips

1. **Embrace the Event-Driven Mindset**: Most communication happens through events. When you see a component doing something, ask "what event caused this?" and "what events might this produce?"

2. **Respect the Boundaries**: Notice how components are isolated - agents have their own workspaces, the event system decouples publishers from subscribers, etc.

3. **Look for the "Seams"**: Pay attention to where components connect - these are often the most interesting parts of the system (e.g., how the reconciler talks to the event store, how agents get their configuration).

4. **Use the Documentation**: Docstrings and comments often contain important insights about why things are done a certain way.

5. **Experiment**: The best way to understand is to try changing something and see what happens. Start with small, safe changes (like adding logging) and work your way up.

By following this navigation guide and studying the codebase in the recommended order, you'll develop a deep understanding of how remora-v2 works as a reactive agent substrate for code processing. Happy exploring!