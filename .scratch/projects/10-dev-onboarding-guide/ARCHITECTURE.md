# Architecture Overview

## Core Architectural Patterns

Remora v2's architecture is built around several key patterns that work together to create a reactive agent substrate for code processing.

### 1. Event-Driven Architecture (EDA)
The foundation of remora-v2 is an event-driven architecture where:
- **All state changes are represented as events**
- Events are persisted in an append-only event store
- Events are distributed to interested subscribers
- Agents react to events in their isolated execution contexts

This pattern enables loose coupling between components, as they communicate solely through events rather than direct method calls.

### 2. Layered Architecture
The system is organized into distinct layers, each with a specific responsibility:

```
┌─────────────────────┐
│   Interface Layer   │  ← CLI, Web Server, LSP Adapter
└─────────────────────┘
┌─────────────────────┐
│ Application Layer   │  ← Services, Runners, Use Cases
└─────────────────────┘
┌─────────────────────┐
│   Domain Layer      │  ← Nodes, Agents, Events, Core Logic
└─────────────────────┘
┌─────────────────────┐
│ Infrastructure Layer│  │ Database, Filesystem, Parsing, Network
└─────────────────────┘
```

### 3. Actor Model for Concurrency
Each agent gets its own isolated processing unit following the actor model:
- Agents process one event at a time from their personal queue
- Eliminates race conditions within an agent's context
- Location transparency: agents don't need to know where other agents are
- Failure isolation: issues in one agent don't directly affect others

### 4. CQRS (Command Query Responsibility Segregation)
The system separates concerns for modifying state vs. reading state:
- **Commands**: Events that cause state transitions (NodeDiscovered, AgentComplete, etc.)
- **Queries**: API endpoints and graph traversals that read state without modifying it
- This separation allows each concern to be optimized independently

### 5. Dependency Injection
Components declare their dependencies explicitly through constructors:
- Services are assembled and wired in the `RuntimeServices` container
- Configuration flows downward from config objects
- Makes the system more testable and maintainable

## Data Flow Through the System

Understanding how information moves through remora-v2 helps clarify the architecture. Let's trace a typical scenario: a file change leading to agent execution.

### 1. File Change Detection → Event Generation
```
File System Change
         ↓
FileReconciler (watches for changes)
         ↓
discovers() → Identifies added/modified/deleted files
         ↓
project_nodes() → Converts discoveries to CodeNode objects
         ↓
EventStore.append() → Publishes NodeDiscovered/NodeChanged/NodeRemoved events
```

### 2. Event Distribution → Agent Notification
```
EventStore
         ↓
Persists event to SQLite database
         ↓
Fans out to EventBus (in-memory distribution)
         ↓
Triggers dispatcher checks subscriptions
         ↓
Matching agents receive events in their inboxes
```

### 3. Agent Processing → State Updates
```
AgentActor
         ↓
Pulls event from inbox
         ↓
Validates cooldown and depth policies
         ↓
Creates isolated workspace
         ↓
Loads agent configuration/bundle
         ↓
Discovers available tools
         ↓
Executes LLM kernel with proper context
         ↓
Emits AgentComplete/AgentError events
         ↓
Resets agent status to IDLE
```

### 4. State Persistence → Storage Layer
```
Event Store
         ↓
Saves all events to events table
         ↓
Node Store
         ↓
Updates/inserts code elements in nodes table
         ↓
Agent Store
         ↓
Updates agent status in agents table
         ↓
Subscription Registry
         ↓
Maintains event→agent routing rules
```

## Key Architectural Decisions and Why They Matter

### Why Event-Driven?
- **Decoupling**: Components don't need direct references to communicate
- **Extensibility**: New listeners can be added without changing existing code
- **Auditability**: Complete history of all changes is maintained
- **Replayability**: System state can be rebuilt by replaying events
- **Responsiveness**: Enables real-time reaction to changes

### Why SQLite for Persistence?
- **Simplicity**: Single file, zero configuration for development
- **Reliability**: ACID transactions ensure data consistency
- **Sufficient Performance**: Adequate for the expected workload
- **Portability**: Easy backup, versioning, and deployment
- **Familiarity**: Well-understood technology with rich tooling

### Why Tree-sitter for Code Discovery?
- **Incremental Parsing**: Efficiently reparses only changed parts of files
- **Language Support**: Official grammars for many languages
- **Concrete Syntax Trees**: Preserves all source code details (including whitespace and comments)
- **Query Language**: Powerful .scm query syntax for defining what to extract
- **Error Tolerance**: Can parse and provide useful structure even for broken code

### Why Asyncio for Concurrency?
- **Performance**: High throughput for I/O-bound operations (typical in agent systems)
- **Resource Efficiency**: Lightweight compared to threading
- **Python Native**: No external dependencies, excellent ecosystem integration
- **Structured Concurrency**: Modern asyncio provides good primitives for managing concurrent tasks
- **Compatibility**: Works well with the event-driven model

## Component Responsibilities

Let's look at what each major part of the system does:

### Discovery Layer (`src/remora/code/`)
- **discovery.py**: Tree-sitter based parsing of source files to find code elements
- **paths.py**: Utilities for resolving configured discovery and query paths
- **projections.py**: Converts discovered CST nodes into persistent CodeNode objects
- **reconciler.py**: Monitors filesystem changes and keeps the node graph in sync

### Core Domain (`src/remora/core/`)
- **node.py**: Data models for code elements, agents, and combined views
- **types.py**: Shared enums, status transitions, and basic types
- **events/**: Event system infrastructure (types, bus, store, dispatcher, subscriptions)
- **graph.py**: Persistent storage for nodes (code elements) and agents
- **runner.py**: Manages agent actors and routes events to them
- **actor.py**: Implements the agent execution model with inboxes and processing loops
- **workspace.py**: Manages isolated agent workspaces using Cairn
- **services.py**: Dependency injection container that assembles all runtime services
- **externals.py**: API surface available to agent tool scripts
- **grail.py**: Integration with external tool discovery systems
- **kernel.py**: Interface to LLM providers for agent reasoning

### Interface Layer
- **web/**: Starlette-based web server with REST APIs and SSE streaming
- **lsp/**: Language Server Protocol adapter for editor integration
- **__main__.py**: Typer-based CLI entry point (`remora start`, `remora discover`)

## Important Architectural Guarantees

The architecture provides several important guarantees that developers can rely on:

1. **Eventual Consistency**: While there may be brief delays, all components eventually converge to the same state
2. **Atomic Event Processing**: Each agent processes events one at a time, guaranteeing sequential handling per agent
3. **Persistence Durability**: Once an event is stored in the EventStore, it will not be lost
4. **Workspace Isolation**: Agents cannot accidentally access each other's private workspaces
5. **Type Safety**: Pydantic models and Python type hints catch many errors at development time
6. **Backpressure Handling**: The system uses semaphores and queues to prevent overload

## How to Study the Architecture

To best understand how remora-v2's architecture works in practice, I recommend studying these components in this order:

1. **Start with the data models** (`src/remora/core/node.py`) to understand what represents code and agents
2. **Look at the event system** (`src/remora/core/events/`) to see how communication happens
3. **Examine the storage layer** (`src/remora/core/graph.py`) to see how state persists
4. **Study the reconciliation process** (`src/remora/code/reconciler.py`) to see how the system stays in sync with the filesystem
5. **Review the agent execution model** (`src/remora/core/actor.py` and `src/remora/core/runner.py`) to see how agents actually work
6. **Finally, look at the interfaces** (`src/remora/web/`, `src/remora/lsp/`, `src/remora/__main__.py`) to see how users and external systems interact

This progression follows the data flow from discovery → persistence → event distribution → agent execution → interface, giving you a complete picture of how the system operates.

In the next section, we'll dive deeper into each of these subsystems with detailed walkthroughs.