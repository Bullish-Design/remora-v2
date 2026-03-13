# Key Subsystems Walkthrough

Let's dive deep into each of remora-v2's key subsystems. Understanding these will give you a comprehensive view of how the library works.

## 1. Discovery and Reconciliation System

This subsystem is responsible for keeping the internal graph of code elements in sync with the actual files on disk.

### Core Components
- **discovery.py**: Tree-sitter based parsing to find code elements
- **paths.py**: Path resolution utilities
- **projections.py**: Converts raw discoveries to persistent nodes
- **reconciler.py**: Main reconciliation loop that detects changes and updates the system

### How It Works: A Step-by-Step Walkthrough

#### Startup Initialization
When remora-v2 starts:
1. `FileReconciler.full_scan()` is called
2. This calls `reconcile_cycle()` which:
   - Collects current file modification times from discovery paths
   - Compares with previous state (empty on first run)
   - For each file, calls `_reconcile_file()`

#### File Reconciliation Process (`_reconcile_file`)
For each file that needs processing:
1. **Discovery Phase**:
   ```python
   discovered = discover(
       [Path(file_path)],
       language_map=self._config.language_map,
       query_paths=resolve_query_paths(...),
       ignore_patterns=...,
       languages=...,
   )
   ```
   This uses tree-sitter to parse the file and extract code elements based on language-specific queries

2. **State Comparison**:
   - Compares `discovered` set with previous state stored in `self._file_state`
   - Identifies additions (newly discovered), deletions (no longer present), and modifications (same element but changed content)

3. **Projection**:
   ```python
   projected = await project_nodes(
       discovered,
       self._node_store,
       self._workspace_service,
       self._config,
   )
   ```
   This converts the raw CSTNode discoveries into persistent CodeNode objects, handling things like:
   - Computing source hashes for change detection
   - Mapping node types to bundle configurations
   - Provisioning agent workspaces for new nodes

4. **Event Generation**:
   - For additions: Creates and publishes `NodeDiscoveredEvent`
   - For modifications with content changes: Creates and publishes `NodeChangedEvent`
   - For deletions: Creates and publishes `NodeRemovedEvent` after cleanup

5. **State Update**:
   - Updates `self._file_state[file_path]` with current mtime and set of node IDs

### Key Insights About Discovery

#### Tree-sitter Integration
The discovery system uses tree-sitter through these steps in `_parse_file`:
1. Determine language from file extension using `language_map`
2. Get the appropriate `LanguagePlugin` from the `LanguageRegistry`
3. Create a `Parser` with the language's grammar
4. Parse the source bytes into a syntax tree
5. Load the appropriate query file (.scm) for the language
6. Execute the query against the syntax tree to find matches
7. Process matches to extract node information (name, type, position, etc.)
8. Build hierarchical names by walking the syntax tree parents
9. Generate unique node IDs based on file path and full name
10. Create `CSTNode` objects with all the extracted information

#### Query Files (.scm)
These are tree-sitter query files that define what to extract from the syntax tree. For example, a Python query might look like:
```
[
  (function_definition
    name: (identifier) @node.name) @node
  (class_definition
    name: (identifier) @node.name) @node
]
```
This tells tree-sitter to capture function and class definitions, binding the node itself to `@node` and the name to `@node.name`.

#### Node ID Generation
Node IDs are generated as `{file_path}::{full_name}` with collision handling:
- If a duplicate ID is detected, append `@{start_byte}` to make it unique
- This ensures every code element has a stable, predictable ID

### Important Files to Study
1. `src/remora/code/discovery.py` - Core parsing logic
2. `src/remora/code/reconciler.py` - Main reconciliation loop
3. `src/remora/code/projections.py` - Conversion to persistent nodes
4. `src/remora/code/paths.py` - Path resolution utilities
5. Any .scm files in configured query_paths to understand what gets discovered

## 2. Agent Execution Model

This subsystem handles how agents receive events, process them, and execute autonomous behavior.

### Core Components
- **actor.py**: Implements `AgentActor` (per-agent processing loop) and `Outbox` (event emission)
- **runner.py**: Manages the registry of agents and routes events to them
- **externals.py**: Defines the API available to agent tool scripts
- **kernel.py**: Interface to LLM providers for agent reasoning
- **workspace.py**: Manages isolated agent workspaces

### How It Works: A Step-by-Step Walkthrough

#### Agent Registration
Agents are created automatically when new code elements are discovered:
1. In `FileReconciler._reconcile_file()`, after projection:
   ```python
   for node_id in additions:
       node = projected_by_id[node_id]
       await self._register_subscriptions(node)
       await self._ensure_agent(node)  # Creates agent if needed
   ```
2. `_ensure_agent()` checks if an agent exists for the node ID
3. If not, it creates a basic `Agent` model and saves it via `AgentStore.upsert_agent()`

#### Event Routing to Agents
When an event is published:
1. `EventStore.append()` saves the event to the database
2. It emits the event to the `EventBus` (in-memory subscribers)
3. It dispatches the event to the `TriggerDispatcher`
4. The dispatcher checks which agents have subscriptions matching the event
5. For each matching agent, it calls the router callback (set by `AgentRunner`)
6. The router puts the event into the agent's inbox (`asyncio.Queue`)

#### Agent Processing Loop (`AgentActor._run`)
Each agent has its own processing loop:
1. Wait for next event from `self.inbox.get()`
2. Update `self._last_active` timestamp
3. Generate correlation ID if not present
4. Check if triggering is allowed via `_should_trigger()` (cooldown/depth policies)
5. If allowed, create an `Outbox` and `Trigger` object
6. Call `_execute_turn()` to process the event

#### Event Processing (`_execute_turn`)
This is where the actual agent work happens:
1. Acquire semaphore slot (limits global concurrency)
2. Retrieve the current `CodeNode` from `NodeStore`
3. Ensure an agent exists in `AgentStore` (create if needed)
4. Transition both node and agent to `RUNNING` status
5. Emit `AgentStartEvent` via the outbox
6. Get or create the agent's workspace
7. Read bundle configuration (`_bundle/bundle.yaml`)
8. Discover available tools in the workspace
9. Build the prompt for the LLM (node info + trigger details)
10. Create LLM kernel with appropriate configuration
11. Run the kernel with messages, tools, and turn limit
12. Extract response text from the result
13. Emit `AgentCompleteEvent` with result summary
14. Handle any exceptions by emitting `AgentErrorEvent`
15. Finally, reset both node and agent status to `IDLE`
16. Update depth tracking for correlation-based recursion limits

### Key Insights About Agent Execution

#### The Outbox Pattern
The `Outbox` class is a clever abstraction that:
- Tags events with actor metadata (actor_id, correlation_id, sequence number)
- Writes through immediately to the `EventStore` (not a buffer)
- Provides a clean separation between event creation and persistence
- Makes it easy to test with `RecordingOutbox` which captures events without persisting

#### Workspace Isolation
Each agent gets its own isolated filesystem view:
- Primary workspace where the agent can read/write files
- Optional stable workspace that provides read-through access to shared files
- This prevents agents from interfering with each other while allowing access to common resources
- Implementation uses the Cairn library which provides sophisticated filesystem capabilities

#### Tool Discovery and Execution
Agents can discover and execute tools:
- Tools are Python files with special conventions (often ending in `.pym`)
- Located in `_bundle/tools/` within the agent's workspace
- The `discover_tools()` function finds and loads these tools
- Tools are made available to the LLM kernel so agents can use them
- This enables agents to perform actions beyond just text generation

#### Concurrency and Throttling
- **Global concurrency**: Controlled by `AgentRunner._semaphore` (default: 4)
- **Per-agent cooldown**: Minimum time between triggers for the same agent (`trigger_cooldown_ms`)
- **Recursion depth**: Limits how deeply agents can trigger each other (`max_trigger_depth`)
- These work together to prevent resource exhaustion and runaway agent chains

### Important Files to Study
1. `src/remora/core/actor.py` - Core agent execution logic
2. `src/remora/core/runner.py` - Agent lifecycle management
3. `src/remora/core/externals.py` - API available to agent tools
4. `src/remora/core/kernel.py` - LLM integration
5. `src/remora/core/workspace.py` - Workspace management
6. Example bundle configurations and tool scripts to understand agent capabilities

## 3. Event System

The event system is the nervous system of remora-v2, enabling communication between all components.

### Core Components
- **events/types.py**: Defines all event types and the base `Event` class
- **events/bus.py**: In-memory publish/subscribe system for real-time distribution
- **events/store.py**: Persistent event storage with database integration
- **events/dispatcher.py**: Routes persisted events to agent inboxes
- **events/subscriptions.py**: Manages event-to-agent routing rules

### How It Works: A Step-by-Step Walkthrough

#### Event Creation and Publishing
When something happens in the system:
1. An event object is created (e.g., `NodeDiscoveredEvent(...)`)
2. `EventStore.append(event)` is called
3. The event is serialized to JSON and stored in the SQLite `events` table
4. The same event object is emitted to the `EventBus` for real-time subscribers
5. The event is dispatched to the `TriggerDispatcher` for agent routing

#### Event Persistence (`EventStore.append`)
1. Convert event to dictionary using `event.model_dump()`
2. Generate a summary using `event.summary()` (often overridden in subclasses)
3. Extract relevant fields (agent_id, from_agent, to_agent, etc.)
4. Insert into SQLite `events` table with JSON payload
5. Return the auto-generated row ID

#### Real-time Distribution (`EventBus`)
The `EventBus` implements a simple but effective pub/sub model:
- Handlers are registered by event type using `subscribe(event_type, handler)`
- A special `subscribe_all(handler)` captures every event
- When `emit(event)` is called:
  - Look up handlers for the exact event type and all its parent classes (via MRO)
  - Look up handlers registered for all events
  - Call all matching handlers, awaiting if they return coroutines

#### Persistent Event Routing (`TriggerDispatcher`)
1. When an event is persisted, `EventStore` calls `dispatcher.dispatch(event)`
2. The dispatcher asks `subscriptions.get_matching_agents(event)` for relevant agent IDs
3. For each matching agent ID, it calls the router callback (provided by `AgentRunner`)
4. The router puts the event into the agent's inbox

#### Subscription Matching (`SubscriptionRegistry`)
This is where the magic of event routing happens:
1. Subscriptions are stored in SQLite with JSON-encoded patterns
2. An in-memory cache indexes subscriptions by event type for fast lookup
3. To find matching agents for an event:
   - Look up subscriptions for the exact event type and wildcard (*)
   - For each subscription, check if the pattern matches the event using:
     - Event type inclusion/exclusion lists
     - From-agent inclusion lists
     - To-agent exact match
     - Path glob matching (using `pathlib.PurePath.match`)
4. Return the list of agent IDs whose subscriptions match

### Key Insights About the Event System

#### Event Design Philosophy
Remora-v2's event system follows these principles:
- **Events are facts**: They represent something that has already happened
- **Events are immutable**: Once created, an event never changes
- **Events are granular**: Each represents a single, discrete occurrence
- **Events are verbose**: They contain all relevant context for handling
- **Events are chronological**: They're stored in order of occurrence

#### Why Both EventBus and EventStore?
This separation serves different purposes:
- **EventBus**: For real-time, in-memory distribution to co-located subscribers
  - Zero persistence, purely for low-latency forwarding
  - Used by components that need to react immediately within the same process
- **EventStore**: For durable persistence and guaranteed delivery
  - Survives process restarts
  - Enables replay, auditing, and offline processing
  - Used as the source of truth for what happened

#### Subscription Pattern Matching
The matching algorithm is surprisingly sophisticated:
- `event_types`: If specified, the event's type must be in this list
- `from_agents`: If specified, the event's `from_agent` field must be in this list
- `to_agent`: If specified, must exactly match the event's `to_agent` field
- `path_glob`: If specified, the event's `path` field must match this glob pattern
- Any field left as `None` acts as a wildcard (don't-care)

This allows for very precise routing while keeping the system flexible.

#### Event Handling Best Practices
Looking at how events are used in the codebase reveals patterns:
- Most event handlers are async (they return coroutines)
- Handlers should be idempotent where possible (safe to run multiple times)
- Handlers should handle missing data gracefully (defensive programming)
- Complex logic should be extracted to separate functions for testability
- Side effects should be minimized and clearly documented

### Important Files to Study
1. `src/remora/core/events/types.py` - All event definitions
2. `src/remora/core/events/bus.py` - In-memory publish/subscribe
3. `src/remora/core/events/store.py` - Persistent storage with real-time distribution
4. `src/remora/core/events/dispatcher.py` - Routing persistent events to agents
5. `src/remora/core/events/subscriptions.py` - Subscription pattern matching logic
6. Look at how various components emit and handle events throughout the codebase

## 4. Persistence Layer

This subsystem handles all durable storage of system state.

### Core Components
- **graph.py**: Storage for code elements (nodes) and agents
- **db.py**: Thin wrapper around SQLite database connection
- **events/store.py**: Event storage (discussed in event system section)
- **subscriptions.py**: Subscription storage (discussed in event system section)

### How It Works: A Step-by-Step Walkthrough

#### Database Initialization
When the system starts:
1. `RuntimeServices.initialize()` is called
2. This calls `create_tables()` on each storage component:
   - `node_store.create_tables()`
   - `agent_store.create_tables()`
   - `subscriptions.create_tables()`
   - `event_store.create_tables()`

#### Table Schemas
Let's look at the key tables:

**nodes table** (stores code elements):
```sql
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    start_byte INTEGER DEFAULT 0,
    end_byte INTEGER DEFAULT 0,
    source_code TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    parent_id TEXT,
    status TEXT DEFAULT 'idle',
    bundle_name TEXT
);
```

**agents table** (stores agent runtime status):
```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    element_id TEXT,
    status TEXT DEFAULT 'idle',
    bundle_name TEXT,
    FOREIGN KEY (element_id) REFERENCES nodes(node_id) ON DELETE SET NULL
);
```

**events table** (stores all events):
```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    agent_id TEXT,
    from_agent TEXT,
    to_agent TEXT,
    correlation_id TEXT,
    timestamp REAL NOT NULL,
    payload TEXT NOT NULL,
    summary TEXT DEFAULT ''
);
```

**subscriptions table** (stores routing rules):
```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    pattern_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

#### Data Access Patterns
The storage classes provide specific methods for their domains:

**NodeStore**:
- `upsert_node(node)`: Insert or update a code element
- `get_node(node_id)`: Retrieve a specific code element
- `list_nodes(filters...)`: Query nodes with various filters
- `delete_node(node_id)`: Remove a code element and its edges
- `set_status(node_id, status)`: Update just the status field
- `transition_status(node_id, target)`: Safely change status with validation
- `add_edge(from_id, to_id, edge_type)`: Create a relationship between nodes
- `get_edges(node_id, direction)`: Get incoming/outgoing/both edges

**AgentStore**:
- Similar patterns but for agent-specific data:
  - `upsert_agent(agent)`
  - `get_agent(agent_id)`
  - `list_agents(status_filter)`
  - `set_status(agent_id, status)`
  - `transition_status(agent_id, target)`
  - `delete_agent(agent_id)`

#### Transaction Handling
Notably, the storage layer does NOT expose explicit transaction control:
- Each method typically executes a single SQL statement
- For multi-step operations, callers must manage consistency themselves
- This keeps the storage layer simple but puts burden on callers
- Some operations like `delete_node` do multiple statements but aren't transactionally wrapped

### Key Insights About Persistence

#### Why Separate NodeStore and AgentStore?
At first glance, this separation might seem odd since agents are closely tied to nodes:
- **Historical reasons**: May have evolved from different concerns
- **Different access patterns**: Nodes are queried frequently by various criteria; agents are mostly accessed by ID for status updates
- **Different lifecycles**: Nodes are relatively permanent; agents come and go more frequently
- **Separation of concerns**: Nodes represent persistent code facts; agents represent transient runtime state

However, as noted in the deep dive analysis, this separation may be unnecessary and could be simplified.

#### Indexing Strategy
Each table has carefully chosen indexes for performance:
- **nodes**: 
  - `idx_nodes_type` on node_type (for filtering by type)
  - `idx_nodes_file` on file_path (for finding nodes in specific files)
  - `idx_nodes_status` on status (for finding idle/running/error agents)
- **agents**:
  - `idx_agents_status` on status (same purpose)
- **edges**:
  - `idx_edges_from` and `idx_edges_to` for efficient traversal
- **events**:
  - `idx_events_type` on event_type (for filtering by type)
  - `idx_events_agent` on agent_id (for finding events related to specific agents)
  - `idx_events_correlation` on correlation_id (for grouping related events)
- **subscriptions**:
  - `idx_subs_agent` on agent_id (for finding subscriptions by agent)

#### Simplicity Over Features
The persistence layer intentionally avoids:
- ORM complexities
- Relationship mapping
- Complex query builders
- Caching layers (except in SubscriptionRegistry)
- Instead, it provides straightforward SQL execution with manual mapping to/from models

This makes the persistence behavior predictable and easy to reason about, though it requires more manual work from callers.

### Important Files to Study
1. `src/remora/core/graph.py` - Node and agent storage
2. `src/remora/core/db.py` - Database connection wrapper
3. `src/remora/core/events/store.py` - Event storage (already covered)
4. `src/remora/core/events/subscriptions.py` - Subscription storage (already covered)
5. Look at how services use these storage components in `src/remora/core/services.py`

## 5. Web Interface

This subsystem provides introspection and control capabilities through HTTP APIs and a browser interface.

### Core Components
- **web/server.py**: Starlette-based web server with API endpoints and SSE streaming
- **web/static/**: Static files for the browser interface (HTML, CSS, JS)
- **lsp/server.py**: Language Server Protocol adapter (related but separate)

### How It Works: A Step-by-Step Walkthrough

#### Server Setup
When the web interface is enabled:
1. In `__main__.py _start()` function:
   ```python
   if not no_web:
       web_app = create_app(
           services.event_store,
           services.node_store,
           services.event_bus,
           project_root=project_root,
       )
       # ... configure and start uvicorn server
   ```
2. `create_app()` builds a Starlette application with various routes

#### Route Handling
The web server exposes several endpoint groups:

**Graph API Endpoints**:
- `GET /api/nodes` → Returns all code elements as JSON
- `GET /api/nodes/{node_id}` → Returns specific code element
- `GET /api/edges` → Returns all relationships between nodes
- `GET /api/nodes/{node_id:path}/edges` → Returns edges for specific node

**Event API Endpoints**:
- `GET /api/events` → Returns recent events (with pagination)
- `GET /sse` → Server-Sent Events stream for real-time updates

**Interaction Endpoints**:
- `POST /api/chat` → Send a message to a specific agent
  - Expects JSON: `{"node_id": "...", "message": "..."}`

#### Server-Sent Events (SSE) Implementation
The `/sse` endpoint provides real-time updates:
1. Client connects and accepts `text/event-stream`
2. Server sends initial `: connected\n\n` to establish connection
3. If `replay` parameter is provided, sends recent events from history
4. If `once` parameter is not set, subscribes to the `EventBus`:
   - For each event received, formats as SSE: `event: {event_type}\ndata: {json}\n\n`
   - Stops if client disconnects

#### Static File Serving
The web interface itself is served as static files:
- `app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")`
- Serves `index.html` and associated assets from the `static/` directory
- The HTML/JavaScript connects to the SSE endpoint and API endpoints to provide a live UI

### Key Insights About the Web Interface

#### API Design Philosophy
The web APIs follow REST-like principles:
- Resource-oriented URLs (`/api/nodes`, `/api/edges`)
- Standard HTTP methods (GET for retrieval, POST for actions)
- JSON request/response bodies
- Appropriate HTTP status codes (200 for success, 400 for bad requests, 404 for not found)
- Consistent error response format: `{"error": "description"}`

#### Real-time Updates with SSE
Server-Sent Events are chosen over WebSockets for simplicity:
- Unidirectional from server to client (perfect for event streaming)
- Built-in browser support with EventSource API
- Automatic reconnect handling
- Simpler to implement and debug than bidirectional WebSockets
- Sufficient for the use case (server pushing events to browser)

#### Security Considerations
The current implementation has minimal security:
- No authentication or authorization
- Binding to localhost only (`127.0.0.1`) by default
- No input validation beyond basic checks
- Intended for local development and trusted environments
- Would need significant hardening for production/external use

#### Integration Points
The web interface integrates with several core systems:
- **NodeStore**: For querying the graph of code elements
- **EventStore**: For accessing historical events and real-time streaming
- **EventBus**: For broadcasting new events to connected clients
- This creates a live view of the system's internal state

### Important Files to Study
1. `src/remora/web/server.py` - Main web server implementation
2. `src/remora/web/static/index.html` - The main browser interface
3. `src/remora/lsp/server.py` - Related LSP functionality (if interested in editor integration)
4. Look at how the web interface is started and configured in `src/remora/__main__.py`

## Putting It All Together: A Complete Scenario

Let's trace a complete scenario to see how all subsystems work together:

### Scenario: A Developer Modifies a Python File

1. **File System Change**: Developer saves changes to `src/myapp/utils.py`
   
2. **Discovery & Reconciliation**:
   - FileReconciler detects the change via watchfiles
   - Calls `discover()` on the modified file using Python tree-sitter grammar
   - Finds that a function `calculate_total()` was modified
   - Projects the discovery to a CodeNode object
   - Compares with previous state and detects content change
   - Publishes `NodeChangedEvent(node_id="src/myapp/utils.py::calculate_total", ...)`

3. **Event System**:
   - EventStore persists the NodeChangedEvent to SQLite
   - EventBus fans it out to any real-time subscribers
   - TriggerDispatcher checks subscriptions and finds agents interested in:
     - NodeChangedEvent type
     - Events with path matching `src/myapp/utils.py`
   - Routes the event to matching agents' inboxes

4. **Agent Execution**:
   - Agent for `src/myapp/utils.py::calculate_total` receives the event
   - Validates it can trigger (not in cooldown, depth OK)
   - Creates isolated workspace and loads bundle configuration
   - Builds prompt showing the changed function and that it was modified
   - Executes LLM kernel with available tools (might include linter, formatter, etc.)
   - Agent decides to run a linter on the modified function
   - Emits AgentCompleteEvent with results

5. **Persistence Layer**:
   - EventStore saves the AgentCompleteEvent
   - NodeStore might update the node's status temporarily during processing
   - AgentStore updates the agent's status through its lifecycle

6. **Web Interface**:
   - Connected browsers receive the NodeChangedEvent via SSE
   - Connected browsers receive the AgentCompleteEvent via SSE
   - User sees the update in real-time in the dashboard
   - User can query the API to see details about the function and agent execution

This scenario demonstrates how all subsystems work in concert to provide remora-v2's reactive agent substrate functionality.

## Recommended Learning Path

To best understand how remora-v2 works, I suggest studying the subsystems in this order:

1. **Start with the data models** (`src/remora/core/node.py`) - Understand what represents code and agents
2. **Study the event system** (`src/remora/core/events/`) - Learn how components communicate
3. **Examine the persistence layer** (`src/remora/core/graph.py`) - See how state is stored durably
4. **Look at discovery and reconciliation** (`src/remora/code/`) - Understand how the system stays in sync with the filesystem
5. **Review the agent execution model** (`src/remora/core/actor.py` and `src/remora/core/runner.py`) - See how agents actually work
6. **Finally, explore the interfaces** (`src/remora/web/`, `src/remora/lsp/`, `src/remora/__main__.py`) - See how users and external systems interact

This progression follows the flow: discover → store → event → act → interface, giving you a complete mental model of the system.

In the next section, we'll cover practical guidance for setting up your development environment and working with the codebase.