# Project 45 — Reorganize `core/` into Sub-Packages

**REMINDER: NO SUBAGENTS. Do all work directly.**

## Goal

Break the flat 22-file `core/` directory into focused sub-packages so a new developer can intuitively find functionality. The public import surface stays the same via re-exports from `core/__init__.py` sub-package `__init__.py` files.

## Target Structure

```
core/
├── __init__.py                 # re-exports for backwards compat
├── model/                      # domain model — what things ARE
│   ├── __init__.py
│   ├── types.py                # StrEnums (NodeStatus, EventType, etc.)
│   ├── node.py                 # Node pydantic model
│   ├── errors.py               # error hierarchy
│   └── config.py               # Config, BundleConfig, etc.
├── events/                     # event system (ALREADY EXISTS — no changes)
│   ├── __init__.py
│   ├── types.py
│   ├── bus.py
│   ├── store.py
│   ├── dispatcher.py
│   └── subscriptions.py
├── agents/                     # agent runtime — how agents execute
│   ├── __init__.py
│   ├── actor.py
│   ├── runner.py
│   ├── turn.py                 # renamed from turn_executor.py
│   ├── kernel.py
│   ├── prompt.py
│   ├── outbox.py
│   └── trigger.py
├── tools/                      # capability & tool system
│   ├── __init__.py
│   ├── capabilities.py         # 7 capability classes (from externals.py)
│   ├── context.py              # TurnContext (from externals.py)
│   └── grail.py
├── storage/                    # persistence layer
│   ├── __init__.py
│   ├── db.py
│   ├── graph.py
│   ├── transaction.py
│   └── workspace.py
├── services/                   # app-level wiring & support
│   ├── __init__.py
│   ├── container.py            # RuntimeServices (from services.py)
│   ├── lifecycle.py
│   ├── search.py
│   ├── rate_limit.py
│   └── metrics.py
└── utils.py                    # deep_merge (stays as-is)
```

## Migration Strategy

**Approach: Move files, then fix imports.** Each step moves one sub-package, updates all internal imports, and verifies tests pass before proceeding. No re-export shims — we update every import site directly.

## Steps

### Phase 1: Create sub-packages and move files

Each step below is atomic: move files → update imports → run tests.

**Step 1: Create `core/model/`**
- Move: `types.py`, `node.py`, `errors.py`, `config.py` → `core/model/`
- Create `core/model/__init__.py` with re-exports
- Update all imports:
  - `from remora.core.types import X` → `from remora.core.model.types import X`
  - `from remora.core.node import X` → `from remora.core.model.node import X`
  - `from remora.core.errors import X` → `from remora.core.model.errors import X`
  - `from remora.core.config import X` → `from remora.core.model.config import X`
- Files to update (source):
  - `core/events/types.py` (imports types)
  - `core/events/store.py` (imports metrics — later step)
  - `core/graph.py` (imports node, types)
  - `core/workspace.py` (imports config, errors, metrics, utils)
  - `core/actor.py` (imports config)
  - `core/runner.py` (imports config)
  - `core/externals.py` (imports events, node, types, etc.)
  - `core/grail.py` (imports workspace)
  - `core/outbox.py` (imports events)
  - `core/prompt.py` (imports config, node, types)
  - `core/search.py` (imports config)
  - `core/services.py` (imports config)
  - `core/trigger.py` (imports config)
  - `core/turn_executor.py` (imports config, errors, types, node)
  - `core/lifecycle.py` (imports config)
  - `code/*.py` (many import config, node, types)
  - `web/*.py` (imports types)
  - `lsp/server.py` (imports types, node)
  - `__main__.py` (imports config)
  - All test files that import config/types/node/errors
- Run: `devenv shell -- pytest`

**Step 2: Create `core/storage/`**
- Move: `db.py`, `graph.py`, `transaction.py`, `workspace.py` → `core/storage/`
- Create `core/storage/__init__.py` with re-exports
- Update all imports:
  - `from remora.core.db import X` → `from remora.core.storage.db import X`
  - `from remora.core.graph import X` → `from remora.core.storage.graph import X`
  - `from remora.core.transaction import X` → `from remora.core.storage.transaction import X`
  - `from remora.core.workspace import X` → `from remora.core.storage.workspace import X`
- Run: `devenv shell -- pytest`

**Step 3: Create `core/agents/`**
- Move: `actor.py`, `runner.py`, `turn_executor.py` (→ `turn.py`), `kernel.py`, `prompt.py`, `outbox.py`, `trigger.py` → `core/agents/`
- Create `core/agents/__init__.py` with re-exports
- Rename `turn_executor.py` → `turn.py` (class stays `AgentTurnExecutor`)
- Update all imports:
  - `from remora.core.actor import X` → `from remora.core.agents.actor import X`
  - `from remora.core.runner import X` → `from remora.core.agents.runner import X`
  - `from remora.core.turn_executor import X` → `from remora.core.agents.turn import X`
  - `from remora.core.kernel import X` → `from remora.core.agents.kernel import X`
  - `from remora.core.prompt import X` → `from remora.core.agents.prompt import X`
  - `from remora.core.outbox import X` → `from remora.core.agents.outbox import X`
  - `from remora.core.trigger import X` → `from remora.core.agents.trigger import X`
- Run: `devenv shell -- pytest`

**Step 4: Create `core/tools/`**
- Split `externals.py`:
  - 7 capability classes → `core/tools/capabilities.py`
  - `TurnContext` + `EXTERNALS_VERSION` → `core/tools/context.py`
- Move: `grail.py` → `core/tools/grail.py`
- Create `core/tools/__init__.py` with re-exports
- Update all imports:
  - `from remora.core.externals import X` → `from remora.core.tools.capabilities import X` or `from remora.core.tools.context import X`
  - `from remora.core.grail import X` → `from remora.core.tools.grail import X`
- Run: `devenv shell -- pytest`

**Step 5: Create `core/services/`**
- Move: `services.py` (→ `container.py`), `lifecycle.py`, `search.py`, `rate_limit.py`, `metrics.py` → `core/services/`
- Rename `services.py` → `container.py`
- Create `core/services/__init__.py` with re-exports
- Update all imports:
  - `from remora.core.services import X` → `from remora.core.services.container import X`
  - `from remora.core.lifecycle import X` → `from remora.core.services.lifecycle import X`
  - `from remora.core.search import X` → `from remora.core.services.search import X`
  - `from remora.core.rate_limit import X` → `from remora.core.services.rate_limit import X`
  - `from remora.core.metrics import X` → `from remora.core.services.metrics import X`
- Run: `devenv shell -- pytest`

**Step 6: Clean up `core/`**
- Only `core/__init__.py` and `core/utils.py` should remain at the top level
- Verify no stale `.py` files left behind
- Final full test run

### Phase 2: Validate

**Step 7: Full test suite + lint**
- `devenv shell -- pytest`
- `devenv shell -- ruff check src/ tests/`
- Verify no import cycles with a quick smoke test

## Import Mapping (Complete Reference)

| Old import path | New import path |
|----------------|-----------------|
| `remora.core.types` | `remora.core.model.types` |
| `remora.core.node` | `remora.core.model.node` |
| `remora.core.errors` | `remora.core.model.errors` |
| `remora.core.config` | `remora.core.model.config` |
| `remora.core.db` | `remora.core.storage.db` |
| `remora.core.graph` | `remora.core.storage.graph` |
| `remora.core.transaction` | `remora.core.storage.transaction` |
| `remora.core.workspace` | `remora.core.storage.workspace` |
| `remora.core.actor` | `remora.core.agents.actor` |
| `remora.core.runner` | `remora.core.agents.runner` |
| `remora.core.turn_executor` | `remora.core.agents.turn` |
| `remora.core.kernel` | `remora.core.agents.kernel` |
| `remora.core.prompt` | `remora.core.agents.prompt` |
| `remora.core.outbox` | `remora.core.agents.outbox` |
| `remora.core.trigger` | `remora.core.agents.trigger` |
| `remora.core.externals` | `remora.core.tools.capabilities` / `remora.core.tools.context` |
| `remora.core.grail` | `remora.core.tools.grail` |
| `remora.core.services` | `remora.core.services.container` |
| `remora.core.lifecycle` | `remora.core.services.lifecycle` |
| `remora.core.search` | `remora.core.services.search` |
| `remora.core.rate_limit` | `remora.core.services.rate_limit` |
| `remora.core.metrics` | `remora.core.services.metrics` |
| `remora.core.utils` | `remora.core.utils` (unchanged) |
| `remora.core.events.*` | `remora.core.events.*` (unchanged) |

## Acceptance Criteria

- All tests pass
- No files remain in `core/` except `__init__.py` and `utils.py`
- Every sub-package has an `__init__.py` with appropriate re-exports
- No import cycles
- Lint passes clean

**REMINDER: NO SUBAGENTS. Do all work directly.**
