# Remora v2 Architecture Analysis

## Core Architectural Patterns

### 1. Event-Driven Architecture
Remora v2 is built around an event-driven architecture where:
- All state changes are represented as events
- Events are persisted in an append-only event store
- Events are fanned out to interested subscribers
- Agents react to events in their inboxes

Key components:
- `EventStore`: Persistent append-only log of all events
- `EventBus`: In-memory pub/sub for real-time event distribution
- `TriggerDispatcher`: Routes persisted events to agent inboxes based on subscriptions
- `SubscriptionRegistry`: Manages event-to-agent routing rules

### 2. Actor Model
Each agent gets its own isolated processing unit:
- `AgentActor`: Processes one event at a time from its inbox
- Sequential processing eliminates race conditions within an agent
- Inbox-based communication prevents direct coupling
- Per-actor state management (cooldowns, depth tracking)

### 3. CQRS (Command Query Responsibility Segregation)
Separation of concerns for state mutations vs. queries:
- Commands: Events that cause state changes (NodeDiscovered, AgentComplete, etc.)
- Queries: API endpoints and graph traversals that read state without modifying it
- Event Store as the write model
- NodeStore/AgentStore as read models derived from events

### 4. Layered Architecture
Clear separation of concerns across layers:
- **Infrastructure Layer**: Database access, filesystem abstractions
- **Domain Layer**: Core business logic (nodes, agents, events, reconciliation)
- **Application Layer**: Use case orchestration (services, runners)
- **Interface Layer**: CLI, web server, LSP adapter

### 5. Dependency Injection
Services are assembled through constructor injection:
- `RuntimeServices` container creates and wires all components
- Configuration flows downward from config objects
- Services declare their dependencies explicitly
- Enables testability through mock injection

## Key Design Decisions

### Immutable Data Models
- `CodeElement` and `CSTNode` use Pydantic's `frozen=True`
- Prevents accidental mutation and enables safe sharing
- Simplifies reasoning about state changes
- Events contain snapshots of state at points in time

### Separation of Discovery and Projection
- Discovery (`discover.py`) finds raw code elements from source
- Projection (`projections.py`) converts discovered elements to domain models
- Allows independent evolution of discovery logic and domain model

### Workspace Isolation
- Each agent gets its own Cairn workspace
- Provides filesystem sandboxing
- Supports read-through to shared stable workspace
- Enables safe, concurrent agent execution

### Event Sourcing Principles
- Events are the primary source of truth
- Current state is derived by replaying events
- Enables audit trails and debugging
- Supports rebuilding state from scratch

## Architectural Strengths

1. **Loose Coupling**: Components communicate through well-defined interfaces
2. **High Cohesion**: Each module has a clear, focused responsibility
3. **Scalability**: Actor model allows horizontal scaling of agent processing
4. **Resilience**: Isolation prevents cascading failures
5. **Observability**: Event streaming provides rich debugging capabilities
6. **Extensibility**: Plugin systems for languages, queries, and tools

## Potential Architectural Improvements

1. **Simplify Event Model**: Some events contain overlapping information
2. **Reduce Indirection**: Several layers of delegation could be flattened
3. **Unify Storage**: Multiple SQLite tables could benefit from better normalization
4. **Streamline Agent Lifecycle**: Complex state transitions could be simplified
5. **Consolidate Configuration**: Configuration is spread across multiple files