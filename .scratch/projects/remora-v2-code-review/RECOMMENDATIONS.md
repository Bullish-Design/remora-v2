# Remora-v2 Recommendations

## Executive Summary

This document provides actionable recommendations for improving the remora-v2 codebase. We prioritize architectural improvements over backward compatibility since the library is still early-stage. These recommendations aim to transform the codebase from "works but messy" to "production-grade elegant."

---

## 1. Architectural Recommendations

### 1.1 Adopt Clean Architecture (Hexagonal/Ports-Adapters)

**Current State**: Business logic is mixed with infrastructure concerns throughout the codebase.

**Recommendation**: Implement clear layers:

```
src/remora/
├── domain/              # Pure business logic, no external deps
│   ├── models/         # Node, Event, Agent entities
│   ├── repositories/   # Abstract interfaces
│   └── services/       # Domain services
├── application/        # Use cases, orchestration
│   ├── ports/          # Input/output interfaces
│   └── services/       # Application services
├── infrastructure/     # External concerns
│   ├── persistence/    # SQLite, file storage
│   ├── web/            # FastAPI/Starlette
│   └── lsp/            # Language server
└── interfaces/         # CLI, Web controllers
```

**Benefits**:
- Clear dependency direction (infrastructure depends on domain, not vice versa)
- Testable without real database/filesystem
- Easy to swap implementations (e.g., PostgreSQL instead of SQLite)

**Migration Path**:
1. Create domain layer with entities
2. Move repository interfaces to domain
3. Implement concrete repositories in infrastructure
4. Refactor services to depend on interfaces

### 1.2 Unify Event System

**Current State**: Three overlapping event systems (EventStore, EventBus, TriggerDispatcher)

**Recommendation**: Single unified event bus with middleware pipeline:

```python
class EventPipeline:
    """Unified event processing pipeline with middleware stages."""
    
    def __init__(self):
        self.stages: list[Middleware] = [
            ValidationMiddleware(),
            PersistenceMiddleware(),  # EventStore
            SubscriptionMiddleware(),  # TriggerDispatcher
            BroadcastMiddleware(),     # EventBus
        ]
    
    async def emit(self, event: Event) -> None:
        ctx = EventContext(event)
        for stage in self.stages:
            await stage.process(ctx)
            if ctx.should_stop:
                break
```

**Benefits**:
- Single source of truth for event flow
- Easy to add/remove stages
- Clear ordering guarantees
- Testable in isolation

### 1.3 Extract Service Composition from RuntimeServices

**Current State**: `RuntimeServices` is a God class that initializes everything

**Recommendation**: Use dependency injection container:

```python
from dependency_injector import containers, providers

class Container(containers.DeclarativeContainer):
    config = providers.Configuration()
    
    db = providers.Singleton(
        lambda cfg: open_database(cfg.db_path),
        config,
    )
    
    node_store = providers.Singleton(
        NodeStore,
        db=db,
    )
    
    event_bus = providers.Singleton(EventBus)
    
    event_store = providers.Singleton(
        EventStore,
        db=db,
        event_bus=event_bus,
    )
    
    # Services compose automatically based on dependencies
```

**Benefits**:
- No manual wiring
- Automatic lifecycle management
- Easy to override for testing
- Type-safe with mypy plugin

---

## 2. Concurrency & Performance Recommendations

### 2.1 Implement Backpressure Throughout

**Current State**: Unbounded queues can cause memory exhaustion

**Recommendation**: Use structured concurrency with backpressure:

```python
from asyncio import Queue
from dataclasses import dataclass

@dataclass
class BackpressureConfig:
    max_queue_size: int = 1000
    overflow_strategy: OverflowStrategy = OverflowStrategy.DROP_OLDEST

class BoundedActor:
    def __init__(self, config: BackpressureConfig):
        self.inbox: Queue[Event] = Queue(maxsize=config.max_queue_size)
        self.config = config
    
    async def send(self, event: Event) -> SendResult:
        try:
            self.inbox.put_nowait(event)
            return SendResult.ACCEPTED
        except QueueFull:
            if self.config.overflow_strategy == OverflowStrategy.RAISE:
                raise BackpressureExceeded()
            elif self.config.overflow_strategy == OverflowStrategy.DROP_OLDEST:
                self.inbox.get_nowait()  # Drop oldest
                self.inbox.put_nowait(event)
                return SendResult.DROPPED_OLDEST
            else:
                return SendResult.DROPPED
```

**Benefits**:
- Predictable memory usage
- Clear failure modes
- Configurable overflow handling

### 2.2 Add Connection Pooling for Database

**Current State**: Single shared connection

**Recommendation**: Use `aiosqlite` with connection pooling or switch to `asyncpg`/`databases`:

```python
from databases import Database

class PooledStorage:
    def __init__(self, database_url: str, pool_size: int = 10):
        self.db = Database(database_url, min_size=5, max_size=pool_size)
    
    async def execute(self, query: str, values: dict) -> Result:
        async with self.db.connection() as conn:
            return await conn.execute(query, values)
```

**Benefits**:
- Better concurrency under load
- Automatic reconnection
- Connection health checks

### 2.3 Implement Batch Operations

**Current State**: Operations are mostly single-row

**Recommendation**: Add bulk operations to repositories:

```python
class NodeRepository:
    async def upsert_many(self, nodes: list[Node]) -> None:
        """Bulk upsert with single transaction."""
        async with self.transaction():
            for batch in chunks(nodes, 100):  # SQLite limit
                await self._db.executemany(
                    "INSERT OR REPLACE INTO nodes ...",
                    [(n.node_id, n.name, ...) for n in batch]
                )
```

**Benefits**:
- 10-100x performance improvement
- Fewer transaction overheads
- Better for reconciliation

---

## 3. Error Handling Recommendations

### 3.1 Use Result Types

**Current State**: Functions return Optional[T] or bool, losing error context

**Recommendation**: Use result types (with `returns` library or custom):

```python
from typing import Generic, TypeVar, Union
from dataclasses import dataclass

T = TypeVar('T')
E = TypeVar('E', bound=Exception)

@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T

@dataclass(frozen=True)
class Err(Generic[E]):
    error: E

Result = Union[Ok[T], Err[E]]

class NodeRepository:
    async def get_node(self, node_id: str) -> Result[Node, NodeNotFoundError]:
        row = await self._db.fetch_one("SELECT * FROM nodes WHERE node_id = ?", node_id)
        if row is None:
            return Err(NodeNotFoundError(node_id))
        return Ok(Node.from_row(row))

# Usage
result = await repo.get_node("some-id")
match result:
    case Ok(node):
        process(node)
    case Err(e):
        logger.error(f"Failed to get node: {e}")
```

**Benefits**:
- Compiler enforces error handling
- Rich error context
- No exceptions for control flow

### 3.2 Implement Circuit Breakers

**Current State**: No protection against cascading failures

**Recommendation**: Add circuit breaker pattern for external calls:

```python
from circuitbreaker import circuit

class ModelClient:
    @circuit(failure_threshold=5, recovery_timeout=60)
    async def call(self, messages: list[Message]) -> Response:
        # If this fails 5 times, circuit opens
        # All subsequent calls fail fast for 60 seconds
        return await self._http_client.post(self.url, json=messages)
```

**Benefits**:
- Prevents cascading failures
- Automatic recovery
- Fail-fast behavior

### 3.3 Structured Logging

**Current State**: Basic logging with manual context formatting

**Recommendation**: Use `structlog` with JSON output:

```python
import structlog

logger = structlog.get_logger()

async def process_turn(self, node_id: str, event: Event):
    logger = logger.bind(
        node_id=node_id,
        event_type=event.event_type,
        correlation_id=event.correlation_id,
    )
    
    logger.info("turn_started", tool_count=len(tools))
    
    try:
        result = await self._execute_turn()
        logger.info("turn_completed", duration_ms=result.duration_ms)
    except ModelError as e:
        logger.error("turn_failed", error=str(e), retryable=e.is_retryable)
        raise
```

**Benefits**:
- Queryable logs
- Automatic correlation
- Structured output for log aggregation

---

## 4. API Design Recommendations

### 4.1 Protocol-First Design

**Current State**: Concrete types used everywhere

**Recommendation**: Define protocols for all public interfaces:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class NodeRepository(Protocol):
    async def get(self, node_id: str) -> Result[Node, NotFoundError]: ...
    async def save(self, node: Node) -> Result[None, StorageError]: ...
    async def list_by_type(self, node_type: NodeType) -> list[Node]: ...

# Implementation
class SQLiteNodeRepository:
    async def get(self, node_id: str) -> Result[Node, NotFoundError]:
        ...
    
    async def save(self, node: Node) -> Result[None, StorageError]:
        ...
    
    async def list_by_type(self, node_type: NodeType) -> list[Node]:
        ...

# Usage - can be SQLite, PostgreSQL, or Mock
class AgentService:
    def __init__(self, repo: NodeRepository):
        self._repo = repo
```

**Benefits**:
- Testability
- Implementation swapping
- Documentation as code

### 4.2 Add API Versioning

**Current State**: No versioning strategy

**Recommendation**: Implement URL-based versioning:

```python
# Current
@router.get("/api/nodes")

# Recommended
@router.get("/api/v1/nodes")
@router.get("/api/v2/nodes")  # New version with breaking changes
```

**Benefits**:
- Graceful evolution
- Client compatibility
- Clear deprecation path

### 4.3 Input Validation Layer

**Current State**: Validation scattered throughout handlers

**Recommendation**: Centralized validation with Pydantic:

```python
from pydantic import BaseModel, Field, validator

class ChatRequest(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=10000)
    
    @validator('node_id')
    def validate_node_id(cls, v):
        if '..' in v or v.startswith('/'):
            raise ValueError('Invalid node_id')
        return v

@app.post("/api/v1/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    # request is already validated
    ...
```

**Benefits**:
- Single source of validation truth
- Automatic error responses
- Self-documenting

---

## 5. Testing Recommendations

### 5.1 Implement Contract Testing

**Current State**: Tests rely on implementation details

**Recommendation**: Test against protocols, not implementations:

```python
import pytest

class TestNodeRepository:
    """Base tests that all implementations must pass."""
    
    @pytest.fixture
    def repo(self) -> NodeRepository:
        raise NotImplementedError
    
    async def test_get_existing_node(self, repo):
        node = Node(...)
        await repo.save(node)
        
        result = await repo.get(node.node_id)
        
        assert result.is_ok()
        assert result.value == node
    
    async def test_get_missing_node(self, repo):
        result = await repo.get("nonexistent")
        
        assert result.is_err()
        assert isinstance(result.error, NotFoundError)

class TestSQLiteNodeRepository(TestNodeRepository):
    @pytest.fixture
    async def repo(self, tmp_path):
        db = await open_database(tmp_path / "test.db")
        yield SQLiteNodeRepository(db)
        await db.close()

class TestInMemoryNodeRepository(TestNodeRepository):
    @pytest.fixture
    def repo(self):
        return InMemoryNodeRepository()
```

**Benefits**:
- One test suite, multiple implementations
- Ensures behavioral consistency
- Makes in-memory implementations viable

### 5.2 Add Property-Based Testing

**Current State**: Only example-based tests

**Recommendation**: Use Hypothesis for property-based tests:

```python
from hypothesis import given, strategies as st
from hypothesis import settings

@given(
    node_ids=st.lists(st.text(), min_size=1, max_size=100),
    events=st.lists(st.builds(Event), min_size=0, max_size=1000)
)
@settings(max_examples=100)
async def test_event_bus_fifo_order(node_ids, events):
    """Events should be processed in order per node."""
    bus = EventBus()
    received = defaultdict(list)
    
    for node_id in node_ids:
        bus.subscribe(node_id, lambda e, nid=node_id: received[nid].append(e))
    
    for event in events:
        await bus.emit(event)
    
    for node_id, event_list in received.items():
        assert event_list == sorted(event_list, key=lambda e: e.timestamp)
```

**Benefits**:
- Finds edge cases
- Tests invariants
- High coverage with few tests

### 5.3 Integration Test Containers

**Current State**: Tests use real SQLite, mock everything else

**Recommendation**: Use testcontainers for integration tests:

```python
from testcontainers.postgres import PostgresContainer
import pytest_asyncio

@pytest_asyncio.fixture
async def postgres_db():
    with PostgresContainer("postgres:15") as postgres:
        url = postgres.get_connection_url()
        db = await create_engine(url)
        yield db
        await db.dispose()

async def test_with_real_database(postgres_db):
    repo = NodeRepository(postgres_db)
    # Tests run against real PostgreSQL in Docker
```

**Benefits**:
- Tests against real infrastructure
- Catches environment-specific issues
- Reproducible environments

---

## 6. Observability Recommendations

### 6.1 Add OpenTelemetry Tracing

**Current State**: No distributed tracing

**Recommendation**: Instrument with OpenTelemetry:

```python
from opentelemetry import trace
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

tracer = trace.get_tracer(__name__)

class Actor:
    async def process_turn(self, event: Event):
        with tracer.start_as_current_span("agent_turn") as span:
            span.set_attribute("node_id", self.node_id)
            span.set_attribute("event_type", event.event_type)
            
            with tracer.start_span("prepare_context"):
                context = await self._prepare_context()
            
            with tracer.start_span("execute_kernel"):
                result = await self._execute(context)
            
            span.set_attribute("turn_duration_ms", result.duration_ms)
```

**Benefits**:
- Performance profiling
- Request tracing
- Dependency mapping

### 6.2 Add Health Checks

**Current State**: Basic health endpoint exists

**Recommendation**: Comprehensive health checks:

```python
from dataclasses import dataclass
from enum import Enum

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass
class HealthCheck:
    name: str
    status: HealthStatus
    latency_ms: float
    details: dict[str, Any]

class HealthChecker:
    def __init__(self):
        self.checks: list[Callable[[], HealthCheck]] = []
    
    async def check_all(self) -> list[HealthCheck]:
        return await asyncio.gather(*[check() for check in self.checks])
    
    async def check_database(self) -> HealthCheck:
        start = time.monotonic()
        try:
            await self._db.execute("SELECT 1")
            return HealthCheck(
                name="database",
                status=HealthStatus.HEALTHY,
                latency_ms=(time.monotonic() - start) * 1000,
                details={}
            )
        except Exception as e:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                latency_ms=(time.monotonic() - start) * 1000,
                details={"error": str(e)}
            )
```

**Benefits**:
- Early problem detection
- Load balancer integration
- SLA monitoring

### 6.3 Metrics Collection

**Current State**: Basic metrics in Metrics class

**Recommendation**: Use Prometheus client:

```python
from prometheus_client import Counter, Histogram, Gauge, Info

# Define metrics
AGENT_TURNS = Counter(
    'remora_agent_turns_total',
    'Total agent turns',
    ['node_type', 'status']
)

TURN_DURATION = Histogram(
    'remora_turn_duration_seconds',
    'Agent turn duration',
    buckets=[.01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]
)

ACTIVE_AGENTS = Gauge(
    'remora_active_agents',
    'Number of active agents'
)

# Usage
async def execute_turn(self):
    with TURN_DURATION.time():
        try:
            result = await self._do_turn()
            AGENT_TURNS.labels(node_type=self.node_type, status="success").inc()
        except Exception:
            AGENT_TURNS.labels(node_type=self.node_type, status="error").inc()
            raise
```

**Benefits**:
- Standard metrics format
- Grafana dashboards
- Alerting integration

---

## 7. Documentation Recommendations

### 7.1 Architecture Decision Records (ADRs)

**Create files**: `docs/adr/`

Document major decisions:
- Why SQLite over PostgreSQL?
- Why three event systems?
- Why custom reconciliation?
- Bundle system design

Template:
```markdown
# ADR-001: SQLite as Primary Storage

## Status
Accepted

## Context
Need embedded database for easy deployment...

## Decision
Use SQLite with WAL mode...

## Consequences
+ Easy deployment
+ Single file
- Limited concurrency
- No horizontal scaling
```

### 7.2 API Documentation

**Recommendation**: OpenAPI/Swagger with automatic generation:

```python
from starlette.applications import Starlette
from starlette.openapi.docs import get_swagger_ui

app = Starlette()

@app.route("/docs")
async def docs(request):
    return get_swagger_ui(
        openapi_url="/openapi.json",
        title="Remora API"
    )

# Or use FastAPI which generates OpenAPI automatically
from fastapi import FastAPI

app = FastAPI(
    title="Remora",
    description="Reactive agent substrate",
    version="2.0.0"
)

@app.get("/api/v1/nodes", response_model=list[NodeResponse])
async def list_nodes() -> list[Node]:
    ...
```

### 7.3 Developer Onboarding

**Create**: `CONTRIBUTING.md`, `docs/development/`

Include:
- Setup instructions
- Architecture overview diagrams
- Testing guidelines
- PR checklist
- Code style guide

---

## 8. Tooling Recommendations

### 8.1 Code Quality Tools

Add to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
select = [
    "E", "F", "W",  # Pyflakes
    "I",            # Isort
    "N",            # Naming
    "D",            # Docstrings
    "UP",           # Pyupgrade
    "B",            # Bugbear
    "C4",           # Comprehensions
    "SIM",          # Simplify
    "ARG",          # Unused arguments
    "ERA",          # Commented code
]

[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_ignores = true
show_error_codes = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "slow: Slow tests",
]
```

### 8.2 Pre-commit Hooks

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

### 8.3 CI/CD Pipeline

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.13"]
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      
      - name: Install dependencies
        run: uv sync --all-extras --dev
      
      - name: Run pre-commit
        run: uv run pre-commit run --all-files
      
      - name: Type check
        run: uv run mypy src/remora
      
      - name: Run tests
        run: uv run pytest --cov=remora --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## 9. Refactoring Roadmap

### Phase 1: Foundation (Weeks 1-2)
- [ ] Add strict type checking with mypy
- [ ] Set up pre-commit hooks
- [ ] Implement unified event pipeline
- [ ] Add input validation layer
- [ ] Fix race conditions in file locking

### Phase 2: Reliability (Weeks 3-4)
- [ ] Implement backpressure throughout
- [ ] Add circuit breakers for external calls
- [ ] Improve error handling with result types
- [ ] Add structured logging
- [ ] Fix memory leaks in event bus

### Phase 3: Performance (Weeks 5-6)
- [ ] Add batch operations to repositories
- [ ] Implement connection pooling
- [ ] Optimize tree-sitter discovery
- [ ] Add caching layer
- [ ] Profile and optimize hot paths

### Phase 4: Architecture (Weeks 7-8)
- [ ] Implement clean architecture layers
- [ ] Add dependency injection
- [ ] Extract protocols for all interfaces
- [ ] Refactor God classes
- [ ] Add event sourcing consideration

### Phase 5: Observability (Weeks 9-10)
- [ ] Add OpenTelemetry tracing
- [ ] Implement comprehensive health checks
- [ ] Add Prometheus metrics
- [ ] Create Grafana dashboards
- [ ] Set up alerting

### Phase 6: Testing (Weeks 11-12)
- [ ] Implement contract testing
- [ ] Add property-based tests
- [ ] Add integration tests with testcontainers
- [ ] Achieve 80%+ test coverage
- [ ] Add load tests

---

## 10. Technology Recommendations

### Consider Adding

1. **FastAPI** - Replace Starlette for better ergonomics and automatic OpenAPI docs
2. **Pydantic v2** - Already using, leverage more features like validators
3. **SQLAlchemy 2.0** - Better than raw aiosqlite for complex queries
4. **arq** - Distributed task queue for background jobs
5. **typer** - Already using, good choice
6. **structlog** - Structured logging
7. **opentelemetry** - Observability
8. **prometheus_client** - Metrics
9. **pytest-asyncio** - Already using
10. **hypothesis** - Property-based testing

### Consider Removing

1. **Global state** - Move to dependency injection
2. **Magic numbers** - Move to configuration
3. **Broad exception catching** - Be specific
4. **String-based routing** - Use enums or types

---

## Summary

This codebase has potential but needs significant investment in:

1. **Architecture** - Clean separation of concerns
2. **Reliability** - Backpressure, circuit breakers, error handling
3. **Observability** - Tracing, metrics, structured logging
4. **Testing** - Contract tests, property tests, integration tests
5. **Tooling** - CI/CD, pre-commit hooks, type checking

The junior developer should be commended for:
- Getting a complex asyncio system working
- Understanding the domain well
- Writing reasonably clean code
- Using modern Python features

But they need mentorship in:
- Software architecture principles
- Production systems design
- Testing strategies
- Performance optimization

**Recommendation**: Assign a senior engineer as mentor. Don't allow feature development until Phase 1-2 (Foundation + Reliability) are complete. This is not punishment—it's setting them up for success.

---

*Document created: 2026-03-18*
*For: Remora-v2 Codebase*
*Priority: High*
