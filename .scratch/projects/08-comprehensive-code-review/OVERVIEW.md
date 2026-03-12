# Remora v2 Library Overview

## What is Remora v2?

Remora v2 is a reactive agent substrate where code nodes (functions, classes, methods, files) can be represented and executed as autonomous agents. It implements an event-driven architecture that enables code elements to react to changes and interact with each other through asynchronous messaging.

## Core Functionality

### 1. Multi-language Code Discovery
- Uses tree-sitter for parsing source code across multiple languages (.py, .md, .toml)
- Supports query overrides for customizing discovery behavior
- Discovers functions, classes, methods, and other code elements as immutable nodes

### 2. Incremental File Reconciliation
- Startup scan to establish initial graph of code elements
- Continuous monitoring for file additions, changes, and deletions
- Maintains synchronization between source files and the internal node graph

### 3. Event-Driven Agent Execution
- Code elements can be associated with autonomous agents
- Agents process events in isolated workspaces
- Sequential processing per agent with concurrency limits
- Event routing based on subscription patterns

### 4. Persistent State Management
- SQLite-backed storage for nodes, agents, subscriptions, and events
- ACID transactions for reliable state persistence
- Schema evolution through table creation scripts

### 5. Web Interface
- Graph visualization of discovered code elements
- Server-Sent Events (SSE) streaming for real-time updates
- REST API for querying nodes, edges, and events
- Chat interface for sending messages to specific agents

## How It Works

### Discovery Process
1. Configure discovery paths in remora.yaml
2. Tree-sitter parses source files using language-specific grammars
3. Queries (.scm files) define what constitutes a node (function, class, etc.)
4. Discovered elements are converted to immutable CSTNodes
5. Nodes are projected into mutable CodeNodes with additional metadata

### Reconciliation Process
1. FileReconciler monitors configured directories for changes
2. On change, re-runs discovery for affected files
3. Compares new discoveries with previous state
4. Generates appropriate events (NodeDiscovered, NodeChanged, NodeRemoved)
5. Updates persistent stores and notifies interested agents

### Agent Execution Process
1. Events are stored in EventStore and fanned out to EventBus
2. TriggerDispatcher matches events to subscription patterns
3. Matching agents receive events in their inboxes via AgentRunner
4. AgentActor processes events sequentially:
   - Validates cooldown and depth constraints
   - Creates isolated workspace for the agent
   - Loads bundle configuration (system prompt, model, etc.)
   - Discovers available tools in the workspace
   - Executes LLM kernel with proper context
   - Emits result events (AgentComplete, AgentError)
   - Resets agent/node status to IDLE

### Web Interface Process
1. Static file serving for the dashboard interface
2. REST APIs for querying graph data (nodes, edges)
3. SSE endpoint for real-time event streaming
4. POST endpoint for sending chat messages to agents
5. EventStore provides persistent event history