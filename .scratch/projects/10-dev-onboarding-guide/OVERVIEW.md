# Remora v2 Library Overview

## What is Remora v2?

Remora v2 is a **reactive agent substrate** where code nodes (functions, classes, methods, files) can be represented and executed as autonomous agents. It enables code elements to react to changes and interact with each other through asynchronous messaging in an event-driven architecture.

Think of it as a system that treats your codebase as a living ecosystem where each significant code element can have its own "agent" that watches for relevant events and can take autonomous actions.

## Core Purpose

The fundamental goal of remora-v2 is to create a system where:
- Code elements are discovered and modeled as persistent entities
- Agents can be attached to these code elements to provide autonomous behavior
- Changes to the codebase trigger events that agents can respond to
- Agents can communicate with each other through message passing
- The system provides introspection and control mechanisms through APIs and a web interface

## Key Capabilities

### 1. Multi-language Tree-sitter Discovery
- Automatically discovers code elements (.py, .md, .toml files) using tree-sitter parsers
- Supports custom query overrides (.scm files) to define what constitutes a "node"
- Discovers functions, classes, methods, and other language-specific constructs
- Maintains an up-to-date graph of discovered code elements

### 2. Incremental File Reconciliation
- Performs initial startup scan to establish the code element graph
- Continuously monitors configured directories for file additions, changes, and deletions
- Generates appropriate events when code elements are discovered, modified, or removed
- Maintains synchronization between the filesystem and the internal node graph

### 3. Event-Driven Agent Execution
- Code elements can have associated autonomous agents
- Agents process events in isolated workspaces
- Event-driven execution model where agents react to relevant occurrences
- Sequential processing per agent with configurable concurrency limits
- Agent lifecycle management (idle → running → complete/error → idle)

### 4. Persistent State Management
- SQLite-backed storage for all system state:
  - Discovered code elements and their properties
  - Agent runtime status and configuration
  - Event history for auditing and replay
  - Subscription rules for event routing
- ACID transactions ensure consistency
- Schema evolves through versioned migration scripts

### 5. Web Interface and APIs
- Graph visualization of discovered code elements and their relationships
- Server-Sent Events (SSE) streaming for real-time updates
- REST API for querying nodes, edges, events, and agent status
- Chat interface for sending messages to specific agents
- Static file serving for the dashboard UI

## How Remora v2 Differs from Traditional Systems

Unlike traditional code analysis tools that run batch processes or linters that operate on demand, remora-v2:
- Maintains a persistent, up-to-date model of your codebase
- Provides continuous, reactive responsiveness to changes
- Enables bidirectional communication between code and tooling
- Treats agents as first-class citizens in the development ecosystem
- Combines static analysis capabilities with dynamic, behavior-driven automation

## Typical Use Cases

1. **Automated Code Review**: Agents that watch for specific code patterns and provide feedback
2. **Live Documentation Generation**: Agents that update documentation when code changes
3. **Dependency Tracking**: Agents that monitor import/require statements and alert on breaking changes
4. **Code Quality Monitoring**: Agents that run linters, formatters, or complexity analyzers on change
5. **Interactive Development Environment**: Agents that provide real-time feedback, suggestions, or refactoring options
6. **Workflow Automation**: Agents that trigger CI/CD processes, deployments, or notifications based on code events

## Technology Stack Highlights

- **Language**: Python 3.8+
- **Parsing**: Tree-sitter for incremental, language-aware code parsing
- **Database**: SQLite for ACID-compliant persistent storage
- **Concurrency**: Asyncio for high-performance async I/O
- **Validation**: Pydantic for data modeling and validation
- **Web**: Starlette for lightweight async web framework
- **Filesystem**: Cairn for isolated agent workspaces
- **CLI**: Typer for beautiful command-line interfaces

In the following sections, we'll dive deeper into how these capabilities work together to create the remora-v2 reactive agent substrate.