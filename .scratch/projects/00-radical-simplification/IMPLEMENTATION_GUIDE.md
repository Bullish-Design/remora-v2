# Remora v2 — Implementation Guide

A complete, step-by-step guide to building the Remora library from scratch.
Written for a developer who has never seen the codebase. Every concept is
explained from first principles.

---

## Table of Contents

### Part I: Concepts
1. [What Remora Is](#1-what-remora-is) — The 30-second explanation
2. [The Mental Model](#2-the-mental-model) — How the pieces fit together
3. [Key External Libraries](#3-key-external-libraries) — What we depend on and why
4. [The Bundle-in-Workspace Pattern](#4-the-bundle-in-workspace-pattern) — How agents own their own config

### Part II: Core Substrate (Phase 1–3)
5. [Project Setup](#5-project-setup) — Repo structure, pyproject.toml, dev tooling
6. [core/config.py — Configuration](#6-coreconfigpy--configuration) — Loading and validating project settings
7. [core/node.py — CodeNode Model](#7-corenodepy--codenode-model) — The data model for every agent
8. [core/events.py — Events, Bus, and Subscriptions](#8-coreeventspy--events-bus-and-subscriptions) — The nervous system
9. [core/graph.py — NodeStore](#9-coregraphpy--nodestore) — Persistent graph of agents
10. [core/kernel.py — LLM Kernel](#10-corekernelpy--llm-kernel) — Wrapping the structured_agents kernel
11. [core/workspace.py — Cairn Workspaces](#11-coreworkspacepy--cairn-workspaces) — Per-agent sandboxed filesystems
12. [core/grail.py — Tool Loading](#12-coregrailpy--tool-loading) — Discovering and wrapping .pym scripts
13. [core/runner.py — The Agent Runner](#13-corerunnerpy--the-agent-runner) — The heart of the system
14. [The Externals Contract](#14-the-externals-contract) — The API between Python and .pym tools

### Part III: Code Plugin (Phase 4)
15. [code/discovery.py — Tree-Sitter Scanning](#15-codediscoverypy--tree-sitter-scanning) — Parsing source into nodes
16. [code/projections.py — CSTNode to CodeNode](#16-codeprojectionspy--cstnode-to-codenode) — Mapping discoveries to the graph
17. [code/reconciler.py — File Watching](#17-codereconcilerpy--file-watching) — Keeping the graph in sync

### Part IV: Tool Bundles (Phase 2–4)
18. [Writing .pym Tools](#18-writing-pym-tools) — The Grail scripting language
19. [System Tools](#19-system-tools) — send_message, subscribe, broadcast, query_agents
20. [Code Tools](#20-code-tools) — rewrite_self, scaffold
21. [Companion Tools](#21-companion-tools) — summarize, categorize, find_links, reflect
22. [Template Bundles](#22-template-bundles) — bundle.yaml format and how templates work

### Part V: Surfaces (Phase 5–6)
23. [web/server.py — HTTP + SSE](#23-webserverpy--http--sse) — The real-time web interface
24. [web/views.py — Graph Visualization](#24-webviewspy--graph-visualization) — Rendering the live graph
25. [lsp/server.py — LSP Adapter](#25-lspserverpy--lsp-adapter) — Optional Neovim integration
26. [CLI Entry Point](#26-cli-entry-point) — Starting Remora from the terminal

### Part VI: Testing & Operations
27. [Testing Strategy](#27-testing-strategy) — Unit, integration, and contract tests
28. [Data Flow Walkthrough](#28-data-flow-walkthrough) — Following a trigger from start to finish
29. [Glossary](#29-glossary) — Every term defined in one place

---

## Part I: Concepts

---

## 1. What Remora Is

Imagine you have a Python project with 50 functions and 10 classes. Now imagine
that every single one of those functions and classes is an **autonomous AI agent**
with:

- Its own **identity** (it knows what code it is, where it lives, who calls it)
- Its own **filesystem** (a private sandbox where it can read/write notes, config, history)
- Its own **tools** (small scripts it can run to do things like rewrite its own code, message other agents, or subscribe to events)
- Its own **mailbox** (it receives events when things change — a file was saved, another agent sent it a message, a human asked it a question)

When something happens — a file changes, a human sends a message, another agent
broadcasts a request — the system finds every agent that cares about that event,
wakes it up, gives it its tools and context, runs an LLM turn, and lets it act.

**Remora is the engine that makes all of this work.**

It has five jobs:
1. **Store the graph** of agents (which nodes exist, how they relate)
2. **Store and route events** (what happened, who cares)
3. **Manage workspaces** (give each agent its own Cairn filesystem)
4. **Run agent turns** (trigger → load tools → call LLM → handle tool calls → emit results)
5. **Show the human what's happening** (web UI with live graph + companion panels)

Everything the agents actually *do* — their behavior, their decisions, their
actions — is defined in `.pym` Grail tool scripts, not in the Python library.
The Python library is the substrate; the `.pym` scripts are the intelligence.

---

## 2. The Mental Model

Here is the complete data flow, from source files to agent actions:

```
 SOURCE FILES (*.py, *.js, *.rs, ...)
       │
       ▼
 ┌─────────────────────┐
 │  code/discovery.py  │  tree-sitter parses source → CSTNode objects
 └─────────┬───────────┘
           │
           ▼
 ┌─────────────────────┐
 │ code/projections.py │  CSTNode → CodeNode (the agent data model)
 └─────────┬───────────┘
           │
           ▼
 ┌─────────────────────┐
 │   core/graph.py     │  NodeStore: persists CodeNodes + edges in SQLite
 │   (NodeStore)       │  Each new node gets a Cairn workspace + template bundle
 └─────────┬───────────┘
           │
           ▼
 ┌─────────────────────┐
 │  core/events.py     │  EventStore: append-only event log (SQLite)
 │  (EventStore +      │  EventBus: in-memory pub/sub for real-time listeners
 │   EventBus +        │  SubscriptionRegistry: "agent X cares about event Y"
 │   Subscriptions)    │
 └─────────┬───────────┘
           │  event arrives → subscription match → trigger
           ▼
 ┌─────────────────────┐
 │   core/runner.py    │  AgentRunner:
 │   (AgentRunner)     │    1. Load the triggered CodeNode from NodeStore
 │                     │    2. Get its AgentWorkspace from CairnWorkspaceService
 │                     │    3. Read _bundle/bundle.yaml for system prompt + config
 │                     │    4. Discover .pym tools from _bundle/tools/
 │                     │    5. Build externals dict (workspace + graph + event ops)
 │                     │    6. Create LLM kernel (structured_agents.AgentKernel)
 │                     │    7. Run the kernel with tools → LLM decides what to do
 │                     │    8. Tool calls execute via externals
 │                     │    9. Emit result events back to EventStore
 └─────────┬───────────┘
           │
           ▼
 ┌─────────────────────┐
 │   web/server.py     │  SSE stream pushes events to browser in real time
 │   (HTTP + SSE)      │  Graph viz shows nodes + edges + status
 │                     │  Companion panel shows agent workspace + chat
 └─────────────────────┘
```

### The key insight

The Python library only handles **plumbing**: store data, route events, manage
filesystems, call the LLM. All **decisions** about what an agent should do are
made by the LLM, using `.pym` tools as its actions. The tools themselves are
tiny scripts (15–25 lines each) that call back into the Python library via
**externals** — a fixed set of ~16 async functions the tool can invoke.

### The lifecycle of an agent

1. **Born**: tree-sitter discovers a function/class in source code
2. **Provisioned**: a template bundle is copied into its new Cairn workspace
3. **Subscribed**: default subscriptions are registered (direct messages, file changes)
4. **Triggered**: an event matches a subscription → agent is enqueued
5. **Executed**: the runner loads its tools, calls the LLM, the LLM uses tools
6. **Acts**: the agent might rewrite its own code, message another agent, write notes
7. **Rests**: the turn ends, status returns to "idle", results are stored as events

---

## 3. Key External Libraries

Remora depends on four domain libraries. Understanding what each one does is
essential before writing any code.

### 3.1 structured_agents

**What it is**: An async LLM agent kernel. Handles the message loop: send messages
to an LLM, receive responses, dispatch tool calls, loop until done.

**What we use from it**:

| Import | Purpose |
|--------|---------|
| `AgentKernel` | The core loop: messages + tools → LLM → tool calls → repeat |
| `build_client` | Creates an OpenAI-compatible HTTP client |
| `Message` | A chat message (`role` + `content`) |
| `ToolSchema` | JSON Schema description of a tool (name, description, parameters) |
| `ToolResult` | The result returned after a tool executes |
| `ToolCall` | An LLM's request to call a tool |
| `DecodingConstraint` | Optional grammar/structural constraints on LLM output |
| `ConstraintPipeline` | Applies decoding constraints |
| `NullObserver` | Default no-op event observer |
| `get_response_parser` | Model-specific response parsing |

**Why we don't reimplement it**: The kernel handles retry logic, tool call parsing,
streaming, response parsing across different model APIs, and constrained decoding.
That's hundreds of lines of tricky async code.

### 3.2 Cairn

**What it is**: A workspace manager that provides sandboxed, copy-on-write
filesystems for agents. Each agent gets its own isolated directory-like workspace
backed by the Turso database (similar to SQLite, with better concurrency support - provided via fsdantic/AgentFS).

**What we use from it**:

| Import | Purpose |
|--------|---------|
| `cairn.runtime.workspace_manager.WorkspaceManager` | Creates and manages workspaces |
| `cairn.runtime.workspace_manager.open_workspace` | Opens an existing workspace |
| `cairn.runtime.external_functions.CairnExternalFunctions` | Pre-built file ops for Grail |

**Key concept**: A Cairn workspace is like a virtual filesystem. You can
`read()`, `write()`, `list_dir()`, `exists()`, and `delete()` files in it.
Under the hood it's a Turso db (similar to SQLite, with better concurrency support), not real files on disk. This gives each agent
isolation — one agent's writes never affect another's.

There are two types of workspaces:
- **Stable workspace**: Shared, read-only view of the project files. All agents
  can read from it.
- **Agent workspace**: Per-agent, copy-on-write. When an agent writes a file,
  the write goes to its private workspace; reads fall through to the stable
  workspace if the file isn't in the agent's workspace yet.

### 3.3 Grail

**What it is**: A sandboxed scripting language (`.pym` files) for defining
agent tools. Grail scripts can declare typed inputs, call external functions,
access a virtual filesystem, and return results.

**What we use from it**:

| Import | Purpose |
|--------|---------|
| `grail.GrailScript` | A loaded, ready-to-run script |
| `grail.load(path)` | Load a `.pym` file into a `GrailScript` |
| `grail.Limits` | Resource limits (timeout, memory, etc.) |

**Key concept**: A `.pym` script declares:
- `Input("param_name", type=str)` — typed inputs the LLM provides
- `@external async def func_name(...)` — functions provided by the host (Remora)
- A body that runs, calls externals, and returns a result

When the LLM calls a tool, Remora executes the corresponding `.pym` script,
passing the LLM's arguments as inputs and the externals dict as the available
external functions.

### 3.4 tree-sitter

**What it is**: A fast, incremental parser that produces concrete syntax trees
(CSTs) from source code. Supports many languages via compiled grammar libraries.

**What we use from it**:

| Import | Purpose |
|--------|---------|
| `tree_sitter.Language` | A compiled grammar for a specific language |
| `tree_sitter.Parser` | Parses source text into a syntax tree |
| `tree_sitter.QueryCursor` | Runs pattern queries against a syntax tree |

**Key concept**: We use tree-sitter to discover **code nodes** — functions,
classes, methods, sections, tables — in a project's source files. Each
discovered node becomes a `CSTNode`, which is then mapped to a `CodeNode`
(the agent model). Tree-sitter gives us the node's name, type, location
(file, line range), and source text.

---

## 4. The Bundle-in-Workspace Pattern

This is the most important design pattern in Remora v2. Understanding it is
necessary before implementing the workspace or runner.

### The problem it solves

Every agent needs configuration: a system prompt (personality/instructions),
a model to use, tools to have available, and execution limits. In a naive
design, this config lives in shared files on disk and every agent of the same
type gets identical behavior.

But we want agents to be **autonomous**. A function agent that handles
authentication should behave differently from one that formats dates. Over
time, agents should be able to specialize — adjust their own prompts, create
new tools, change their model.

### How it works

1. **Template bundles** live in the repository under `bundles/`:
   ```
   bundles/
     code-agent/
       bundle.yaml          # system_prompt, model, max_turns, etc.
       tools/
         rewrite_self.pym   # tool for rewriting own source code
         scaffold.pym       # tool for scaffolding new code
     system/
       bundle.yaml
       tools/
         send_message.pym
         subscribe.pym
         ...
   ```

2. **When a node is first discovered**, the provisioning step copies the
   template bundle into the node's Cairn workspace:
   ```
   # Inside agent workspace for node "src/auth.py::validate_token"
   _bundle/
     bundle.yaml            # copied from bundles/code-agent/bundle.yaml
     tools/
       rewrite_self.pym     # copied from bundles/code-agent/tools/
       scaffold.pym
       send_message.pym     # also copied from bundles/system/tools/
       subscribe.pym
       ...
   notes/                   # agent's private scratchpad
   chat/                    # conversation history
   meta/                    # agent-generated metadata
   ```

3. **The runner reads config from the workspace**, not from the filesystem:
   ```python
   bundle_yaml = await workspace.read("_bundle/bundle.yaml")
   config = yaml.safe_load(bundle_yaml)
   system_prompt = config["system_prompt"]
   model = config["model"]
   ```

4. **The agent can modify its own config** via workspace writes:
   ```python
   # Inside a .pym tool, the agent could do:
   current = await read_file("_bundle/bundle.yaml")
   modified = current.replace("You are a code agent", "You are a security auditor")
   await write_file("_bundle/bundle.yaml", modified)
   ```

5. **The agent can even create new tools**:
   ```python
   # A .pym tool that creates another .pym tool:
   tool_code = '''
   Input("query", type=str)
   @external
   async def search_content(pattern, path): ...
   result = await search_content(query, ".")
   return result
   '''
   await write_file("_bundle/tools/search.pym", tool_code)
   ```

### Why this matters

- Every agent starts identical to its type peers (all functions start with the
  same bundle) but can **diverge independently** as it learns about its own code.
- No separate "bundle resolution" logic — just read from the workspace.
- Debugging is trivial: look at the workspace to see exactly what an agent has.
- The "bundle" concept and "workspace" concept are unified — less conceptual
  overhead.

### Template layering

When provisioning, templates are layered:
1. Copy `bundles/system/` tools → `_bundle/tools/` (every agent gets these)
2. Copy `bundles/<type>/` tools → `_bundle/tools/` (type-specific tools)
3. Copy `bundles/<type>/bundle.yaml` → `_bundle/bundle.yaml` (type-specific config)

The system tools and type tools merge into one flat `_bundle/tools/` directory.

---

## Part II: Core Substrate (Phase 1–3)

---

## 5. Project Setup

### 5.1 Repository structure

```
remora-v2/
├── pyproject.toml
├── remora.yaml.example
├── README.md
├── src/
│   └── remora/
│       ├── __init__.py
│       ├── __main__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── node.py
│       │   ├── events.py
│       │   ├── graph.py
│       │   ├── runner.py
│       │   ├── workspace.py
│       │   ├── kernel.py
│       │   └── grail.py
│       ├── code/
│       │   ├── __init__.py
│       │   ├── discovery.py
│       │   ├── reconciler.py
│       │   └── projections.py
│       ├── web/
│       │   ├── __init__.py
│       │   ├── server.py
│       │   └── views.py
│       ├── lsp/
│       │   ├── __init__.py
│       │   └── server.py
│       └── utils/
│           ├── __init__.py
│           ├── fs.py
│           └── paths.py
├── bundles/
│   ├── system/
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       ├── send_message.pym
│   │       ├── subscribe.pym
│   │       ├── unsubscribe.pym
│   │       ├── broadcast.pym
│   │       └── query_agents.pym
│   ├── code-agent/
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       ├── rewrite_self.pym
│   │       └── scaffold.pym
│   └── companion/
│       ├── bundle.yaml
│       └── tools/
│           ├── summarize.pym
│           ├── categorize.pym
│           ├── find_links.pym
│           └── reflect.pym
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_config.py
    │   ├── test_node.py
    │   ├── test_events.py
    │   ├── test_graph.py
    │   ├── test_runner.py
    │   ├── test_workspace.py
    │   └── test_discovery.py
    └── integration/
        ├── test_turn_execution.py
        └── test_reconciler.py
```

### 5.2 pyproject.toml essentials

```toml
[project]
name = "remora"
version = "2.0.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "structured-agents>=0.4",
    "cairn>=0.1",
    "grail>=0.1",
    "tree-sitter>=0.24",
    "starlette>=0.40",
    "uvicorn>=0.30",
    "click>=8.0",
]

[project.optional-dependencies]
lsp = ["pygls>=1.0", "lsprotocol>=2024.0"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.8"]

[project.scripts]
remora = "remora.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/remora"]
```

### 5.3 Development workflow

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev,lsp]"

# Run tests
pytest tests/ -v

# Run linter
ruff check src/ tests/
```

---

## 6. core/config.py — Configuration

### What it does

Loads project-level configuration from `remora.yaml` (or environment variables).
One `Config` object is created at startup and passed to everything that needs it.

### How to implement

Use `pydantic-settings` for automatic env var support and type validation.

```python
"""Project-level configuration."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Remora configuration. Loaded from remora.yaml or environment variables."""

    model_config = SettingsConfigDict(env_prefix="REMORA_")

    # Project
    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None

    # Bundles — maps node_type to template bundle directory name
    bundle_root: str = "bundles"
    bundle_mapping: dict[str, str] = Field(default_factory=lambda: {
        "function": "code-agent",
        "class": "code-agent",
        "method": "code-agent",
        "file": "code-agent",
    })

    # LLM
    model_base_url: str = "http://localhost:8000/v1"
    model_default: str = "Qwen/Qwen3-4B"
    model_api_key: str = ""
    timeout_s: float = 300.0
    max_turns: int = 8

    # Agent execution
    swarm_root: str = ".remora"
    max_concurrency: int = 4
    max_trigger_depth: int = 5
    trigger_cooldown_ms: int = 1000

    # Workspace
    workspace_ignore_patterns: tuple[str, ...] = (
        ".git", ".venv", "__pycache__", "node_modules", ".remora",
    )
```

**Key design choices:**
- `bundle_mapping` replaces the old extension config system. It maps each
  `node_type` (from tree-sitter) to a template bundle directory name.
- All string values support `${VAR:-default}` shell expansion (implement a
  small `_expand_env_vars()` helper that walks the parsed YAML).
- The `Config` class is frozen after construction — never mutated at runtime.

### Loading

```python
def load_config(path: Path | None = None) -> Config:
    """Load config from remora.yaml, walking up directories to find it."""
    if path is None:
        path = _find_config_file()
    if path is None:
        return Config()
    data = yaml.safe_load(path.read_text()) or {}
    return Config(**_expand_env_vars(data))
```

### Testing

```python
def test_default_config():
    config = Config()
    assert config.max_turns == 8
    assert config.bundle_mapping["function"] == "code-agent"

def test_load_from_yaml(tmp_path):
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text("max_turns: 20\nmodel_default: gpt-4")
    config = load_config(yaml_path)
    assert config.max_turns == 20
    assert config.model_default == "gpt-4"
```

---

## 7. core/node.py — CodeNode Model

### What it does

Defines the `CodeNode` Pydantic model — the data model for every agent in the
system. A CodeNode represents a single code element (function, class, method,
file) that has been discovered by tree-sitter and promoted to an agent.

### The model

```python
"""CodeNode — the unified agent data model."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CodeNode(BaseModel):
    """A code element that is also an autonomous agent.

    Every field is explicitly typed. No metadata blobs.
    Serializes to/from SQLite rows.
    """

    model_config = ConfigDict(frozen=False)

    # === Identity (from tree-sitter discovery) ===
    node_id: str                    # deterministic: "file_path::full_name"
    node_type: str                  # "function", "class", "method", "file"
    name: str                       # short name: "validate_token"
    full_name: str                  # qualified: "AuthService.validate_token"
    file_path: str                  # "src/auth/service.py"
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str                # SHA-256 of source_code

    # === Graph context ===
    parent_id: str | None = None    # parent node (class for methods, file for top-level)
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # === Runtime state ===
    status: str = "idle"            # "idle", "running", "error", "pending_approval"

    # === Bundle info ===
    bundle_name: str | None = None  # which template was used to provision

    # === Serialization ===

    def to_row(self) -> dict[str, Any]:
        """Serialize for SQLite INSERT. JSON-encode list fields."""
        data = self.model_dump()
        data["caller_ids"] = json.dumps(data["caller_ids"])
        data["callee_ids"] = json.dumps(data["callee_ids"])
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict) -> CodeNode:
        """Hydrate from a SQLite row. JSON-decode list fields."""
        data = dict(row)
        data["caller_ids"] = json.loads(data.get("caller_ids") or "[]")
        data["callee_ids"] = json.loads(data.get("callee_ids") or "[]")
        return cls(**data)
```

### Design notes

- **`node_id` format**: `"file_path::full_name"` — deterministic, human-readable.
  Example: `"src/auth/service.py::AuthService.validate_token"`.
- **`source_hash`**: SHA-256 hex digest of `source_code`. Used by the reconciler
  to detect when code has changed.
- **No `system_prompt` field**: The prompt lives in the agent's workspace under
  `_bundle/bundle.yaml`, not on the node model.
- **No LSP methods**: No `to_code_lens()`, `to_hover()`, etc. Those belong in
  the LSP adapter, not the data model.
- **`frozen=False`**: The runner needs to update `status`. If you prefer
  immutability, use `model_copy(update={"status": "running"})` instead.

### Testing

```python
def test_codenode_roundtrip():
    node = CodeNode(
        node_id="test.py::foo",
        node_type="function",
        name="foo",
        full_name="foo",
        file_path="test.py",
        start_line=1,
        end_line=5,
        source_code="def foo(): pass",
        source_hash="abc123",
    )
    row = node.to_row()
    assert isinstance(row["caller_ids"], str)  # JSON string
    restored = CodeNode.from_row(row)
    assert restored.node_id == node.node_id
    assert restored.caller_ids == []
```

---

## 8. core/events.py — Events, Bus, and Subscriptions

This is the most complex core module. It contains three things that work together:
**event types**, the **EventBus** (in-memory), and the **EventStore** (SQLite)
with integrated **SubscriptionRegistry**.

### 8.1 Event Types

Events are Pydantic models. They represent things that happen in the system.
All events share a common base:

```python
from __future__ import annotations
from pydantic import BaseModel, Field
import time

class Event(BaseModel):
    """Base event. All events inherit from this."""
    event_type: str = ""           # auto-set from class name if empty
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.event_type:
            self.event_type = type(self).__name__
```

Then define specific event types. Keep them all in one file:

```python
# --- Agent lifecycle ---

class AgentStartEvent(Event):
    agent_id: str
    node_name: str = ""

class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""

class AgentErrorEvent(Event):
    agent_id: str
    error: str

# --- Communication ---

class AgentMessageEvent(Event):
    from_agent: str
    to_agent: str
    content: str

class HumanChatEvent(Event):
    to_agent: str
    message: str

class AgentTextResponse(Event):
    agent_id: str
    content: str

# --- Code changes ---

class NodeDiscoveredEvent(Event):
    node_id: str
    node_type: str
    file_path: str
    name: str

class NodeChangedEvent(Event):
    node_id: str
    old_hash: str
    new_hash: str

class ContentChangedEvent(Event):
    path: str
    change_type: str = "modified"   # "created", "modified", "deleted"

class RewriteProposalEvent(Event):
    agent_id: str
    proposal_id: str
    file_path: str
    old_source: str
    new_source: str
    diff: str = ""

# --- Tools ---

class ToolResultEvent(Event):
    agent_id: str
    tool_name: str
    result_summary: str = ""
```

**Why Pydantic?** Type checking, JSON serialization, IDE autocomplete. Every
event has a known shape. No `dict[str, Any]` guessing.

### 8.2 EventBus

The in-memory pub/sub system. Components subscribe to event *types* and get
called when matching events are emitted. The bus uses Python's MRO (method
resolution order) for inheritance-based matching — subscribing to `Event` gets
you all events.

```python
import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

EventHandler = Callable[[Any], Any]  # sync or async

class EventBus:
    """In-memory event dispatch with type-based subscriptions."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []

    async def emit(self, event: Event) -> None:
        """Dispatch event to all matching handlers."""
        # Walk MRO to find handlers for this type and all parent types
        for event_type in type(event).__mro__:
            for handler in self._handlers.get(event_type, []):
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
        for handler in self._all_handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (used by SSE streaming)."""
        self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions."""
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)

    @asynccontextmanager
    async def stream(self, *event_types: type) -> AsyncIterator[AsyncIterator[Event]]:
        """Async context manager that yields an async iterator of events.

        Usage:
            async with bus.stream(AgentStartEvent) as events:
                async for event in events:
                    print(event)
        """
        queue: asyncio.Queue[Event] = asyncio.Queue()
        filter_set = set(event_types) if event_types else None

        def _enqueue(event: Event) -> None:
            if filter_set is None or any(isinstance(event, t) for t in filter_set):
                queue.put_nowait(event)

        self.subscribe_all(_enqueue)

        async def _iterate() -> AsyncIterator[Event]:
            while True:
                yield await queue.get()

        try:
            yield _iterate()
        finally:
            self.unsubscribe(_enqueue)
```

### 8.3 SubscriptionRegistry

Persistent event routing. Agents register **subscription patterns** that describe
which events they care about. When an event arrives, the registry finds all
matching agents.

```python
class SubscriptionPattern(BaseModel):
    """Pattern for matching events. None fields = match anything."""
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None

    def matches(self, event: Event) -> bool:
        """Check if this pattern matches the given event."""
        if self.event_types and event.event_type not in self.event_types:
            return False
        if self.from_agents:
            from_agent = getattr(event, "from_agent", None)
            if from_agent not in self.from_agents:
                return False
        if self.to_agent:
            to_agent = getattr(event, "to_agent", None)
            if to_agent != self.to_agent:
                return False
        if self.path_glob:
            path = getattr(event, "path", None)
            if path is None or not PurePath(path).match(self.path_glob):
                return False
        return True


class SubscriptionRegistry:
    """SQLite-backed subscription storage with in-memory cache."""

    def __init__(self, connection: sqlite3.Connection, lock: asyncio.Lock):
        self._conn = connection
        self._lock = lock
        self._cache: dict[str, list[tuple[str, SubscriptionPattern]]] | None = None

    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
        """Register a subscription. Returns the subscription ID."""
        ...

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a subscription by ID."""
        ...

    async def get_matching_agents(self, event: Event) -> list[str]:
        """Find all agent IDs whose subscriptions match this event."""
        ...
```

The cache is indexed by `event_type` for O(1) lookup. It's invalidated on any
mutation (register/unregister). This is important for performance — subscription
matching happens on every event append.

### 8.4 EventStore

The durable event log. Append-only SQLite with WAL mode for concurrent reads.

```python
class EventStore:
    """Append-only event log with subscription-based triggers."""

    def __init__(
        self,
        db_path: Path,
        subscriptions: SubscriptionRegistry | None = None,
        event_bus: EventBus | None = None,
    ):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._trigger_queue: asyncio.Queue[tuple[str, Event]] | None = None

    async def initialize(self) -> None:
        """Create tables and set WAL mode."""
        ...

    async def append(self, event: Event) -> int:
        """Append an event. Returns the event ID.

        After appending:
        1. Forward to EventBus (real-time listeners)
        2. Match against subscriptions → enqueue triggers
        """
        ...

    async def get_events(self, limit: int = 100) -> list[dict]:
        """Get recent events."""
        ...

    async def get_events_for_agent(self, agent_id: str, limit: int = 50) -> list[dict]:
        """Get events relevant to a specific agent."""
        ...

    async def get_triggers(self) -> AsyncIterator[tuple[str, Event]]:
        """Yield (agent_id, triggering_event) from the trigger queue."""
        ...
```

**The trigger flow** (the most important thing to understand):

```
event arrives via append()
    │
    ├─► EventBus.emit(event)              # real-time: SSE, UI, etc.
    │
    └─► SubscriptionRegistry.get_matching_agents(event)
            │
            └─► for each matching agent_id:
                    trigger_queue.put((agent_id, event))
                        │
                        └─► AgentRunner consumes from trigger_queue
```

### SQLite schema

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    agent_id TEXT,
    from_agent TEXT,
    to_agent TEXT,
    correlation_id TEXT,
    timestamp REAL NOT NULL,
    payload TEXT NOT NULL,       -- JSON-serialized event
    summary TEXT DEFAULT ''
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_agent ON events(agent_id);
CREATE INDEX idx_events_correlation ON events(correlation_id);

CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    pattern_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX idx_subs_agent ON subscriptions(agent_id);
```

### Testing

```python
@pytest.mark.asyncio
async def test_event_roundtrip(tmp_path):
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    event_id = await store.append(event)
    assert event_id > 0
    events = await store.get_events(limit=1)
    assert events[0]["event_type"] == "AgentMessageEvent"

@pytest.mark.asyncio
async def test_subscription_triggers(tmp_path):
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    # Register: agent "b" wants messages sent to it
    await store.subscriptions.register("b", SubscriptionPattern(to_agent="b"))
    # Append a message to "b"
    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hi")
    await store.append(event)
    # Check trigger queue
    agent_id, trigger_event = await asyncio.wait_for(
        store._trigger_queue.get(), timeout=1.0
    )
    assert agent_id == "b"
```

---

## 9. core/graph.py — NodeStore

### What it does

Persists `CodeNode` objects and their edges in SQLite. This is the graph of
all agents in the system.

### Interface

```python
"""Persistent graph store for CodeNode agents."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from remora.core.node import CodeNode


@dataclass
class Edge:
    """A directed edge between two nodes."""
    from_id: str
    to_id: str
    edge_type: str  # "parent", "calls", "called_by"


class NodeStore:
    """SQLite-backed storage for CodeNode graph."""

    def __init__(self, connection: sqlite3.Connection, lock: asyncio.Lock):
        self._conn = connection
        self._lock = lock

    async def create_tables(self) -> None:
        """Create nodes and edges tables."""
        ...

    async def upsert_node(self, node: CodeNode) -> None:
        """Insert or update a node. Uses node_id as the primary key."""
        row = node.to_row()
        # Use INSERT OR REPLACE
        ...

    async def get_node(self, node_id: str) -> CodeNode | None:
        """Get a single node by ID."""
        ...

    async def list_nodes(
        self,
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
    ) -> list[CodeNode]:
        """List nodes with optional filters."""
        ...

    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and its edges."""
        ...

    async def set_status(self, node_id: str, status: str) -> None:
        """Update just the status field of a node."""
        ...

    async def add_edge(self, from_id: str, to_id: str, edge_type: str) -> None:
        """Add a directed edge."""
        ...

    async def get_edges(
        self, node_id: str, direction: str = "both"
    ) -> list[Edge]:
        """Get edges for a node. direction: 'outgoing', 'incoming', 'both'."""
        ...

    async def delete_edges(self, node_id: str) -> int:
        """Delete all edges involving a node."""
        ...
```

### SQLite schema

```sql
CREATE TABLE nodes (
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
    caller_ids TEXT DEFAULT '[]',     -- JSON array
    callee_ids TEXT DEFAULT '[]',     -- JSON array
    status TEXT DEFAULT 'idle',
    bundle_name TEXT
);

CREATE INDEX idx_nodes_type ON nodes(node_type);
CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_nodes_status ON nodes(status);

CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    UNIQUE(from_id, to_id, edge_type)
);

CREATE INDEX idx_edges_from ON edges(from_id);
CREATE INDEX idx_edges_to ON edges(to_id);
```

### Shared database connection

The `NodeStore` and `EventStore` share the same SQLite database and connection.
This is important — it means all state lives in one `.db` file under `.remora/`.

```python
# In the startup code:
conn = sqlite3.connect(".remora/remora.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
conn.row_factory = sqlite3.Row
lock = asyncio.Lock()

node_store = NodeStore(conn, lock)
await node_store.create_tables()

event_store = EventStore(...)  # same conn
```

### Why asyncio.Lock + asyncio.to_thread?

SQLite doesn't support true async. We use `asyncio.to_thread()` to run SQLite
operations on a thread pool, and `asyncio.Lock()` to serialize writes. Reads
can use a separate connection for concurrency (WAL mode allows concurrent reads).

---

## 10. core/kernel.py — LLM Kernel

### What it does

A thin wrapper around `structured_agents.AgentKernel`. Creates a kernel with
Remora's standard defaults. This module is intentionally tiny (~50 lines).

### Implementation

```python
"""Thin wrapper around structured_agents for LLM kernel creation."""
from __future__ import annotations
from typing import Any

from structured_agents import (
    AgentKernel,
    ConstraintPipeline,
    NullObserver,
    build_client,
    get_response_parser,
)


def create_kernel(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    timeout: float = 300.0,
    tools: list[Any] | None = None,
    observer: Any | None = None,
    grammar_config: Any | None = None,
    client: Any | None = None,
) -> AgentKernel:
    """Create an AgentKernel with standard Remora defaults."""
    if client is None:
        client = build_client({
            "base_url": base_url,
            "api_key": api_key or "EMPTY",
            "model": model_name,
            "timeout": timeout,
        })

    response_parser = get_response_parser(model_name)
    constraint_pipeline = None
    if grammar_config:
        constraint_pipeline = ConstraintPipeline(grammar_config)

    return AgentKernel(
        client=client,
        response_parser=response_parser,
        tools=tools or [],
        observer=observer or NullObserver(),
        constraint_pipeline=constraint_pipeline,
    )


def extract_response_text(result: Any) -> str:
    """Extract text content from a kernel run result."""
    if hasattr(result, "final_message") and result.final_message:
        if hasattr(result.final_message, "content") and result.final_message.content:
            return result.final_message.content
    return str(result)
```

**Why a wrapper?** It centralizes the `build_client` / `get_response_parser` /
`ConstraintPipeline` wiring so the runner doesn't need to know about those details.
If `structured_agents` changes its API, we change one file.

---

## 11. core/workspace.py — Cairn Workspaces

### What it does

Manages per-agent Cairn workspaces. Each agent gets its own sandboxed filesystem
where it stores its bundle config, tools, notes, chat history, and any other
files it creates.

### 11.1 AgentWorkspace

A thin wrapper around a Cairn workspace with convenience methods:

```python
"""Cairn workspace integration for Remora agents."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


class AgentWorkspace:
    """Per-agent sandboxed filesystem backed by Cairn."""

    def __init__(self, workspace: Any, agent_id: str, stable_workspace: Any | None = None):
        self._workspace = workspace
        self._agent_id = agent_id
        self._stable = stable_workspace
        self._lock = asyncio.Lock()  # serialize FS ops (Cairn/AgentFS requirement)

    async def read(self, path: str) -> str:
        """Read a file. Falls through to stable workspace if not found."""
        async with self._lock:
            try:
                return await self._workspace.files.read(path, mode="text")
            except FileNotFoundError:
                if self._stable:
                    return await self._stable.files.read(path, mode="text")
                raise

    async def write(self, path: str, content: str | bytes) -> None:
        """Write a file (copy-on-write isolated to this agent)."""
        async with self._lock:
            await self._workspace.files.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check if a file exists in agent or stable workspace."""
        async with self._lock:
            if await self._workspace.files.exists(path):
                return True
            if self._stable:
                return await self._stable.files.exists(path)
            return False

    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries, merging agent and stable workspaces."""
        async with self._lock:
            entries = set(await self._workspace.files.list_dir(path, output="name"))
            if self._stable:
                try:
                    entries.update(await self._stable.files.list_dir(path, output="name"))
                except Exception:
                    pass
            return sorted(entries)

    async def delete(self, path: str) -> None:
        """Delete a file from the agent workspace."""
        async with self._lock:
            await self._workspace.files.remove(path)
```

### 11.2 CairnWorkspaceService

Manages the lifecycle of all workspaces. Creates and caches agent workspaces.

```python
from cairn.runtime import workspace_manager as cairn_wm


class CairnWorkspaceService:
    """Manages stable and per-agent Cairn workspaces."""

    def __init__(self, config: Config, project_root: Path):
        self._config = config
        self._project_root = project_root.resolve()
        self._swarm_root = project_root / config.swarm_root
        self._manager = cairn_wm.WorkspaceManager()
        self._stable: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the stable workspace."""
        self._swarm_root.mkdir(parents=True, exist_ok=True)
        self._stable = await cairn_wm.open_workspace(
            str(self._swarm_root / "stable")
        )

    async def get_agent_workspace(self, node_id: str) -> AgentWorkspace:
        """Get or create an agent's workspace."""
        async with self._lock:
            if node_id in self._agent_workspaces:
                return self._agent_workspaces[node_id]
            ws = await cairn_wm.open_workspace(
                str(self._swarm_root / "agents" / _safe_id(node_id))
            )
            agent_ws = AgentWorkspace(ws, node_id, self._stable)
            self._agent_workspaces[node_id] = agent_ws
            return agent_ws

    async def provision_bundle(
        self, node_id: str, template_dirs: list[Path]
    ) -> None:
        """Copy template bundle files into the agent's workspace.

        Called once when a node is first discovered. template_dirs
        is ordered: system bundle first, then type-specific bundle.
        Later dirs override earlier ones for bundle.yaml.
        """
        ws = await self.get_agent_workspace(node_id)
        for template_dir in template_dirs:
            if not template_dir.exists():
                continue
            # Copy bundle.yaml
            bundle_yaml = template_dir / "bundle.yaml"
            if bundle_yaml.exists():
                await ws.write(
                    "_bundle/bundle.yaml",
                    bundle_yaml.read_text(encoding="utf-8"),
                )
            # Copy tools
            tools_dir = template_dir / "tools"
            if tools_dir.exists():
                for pym_file in tools_dir.glob("*.pym"):
                    await ws.write(
                        f"_bundle/tools/{pym_file.name}",
                        pym_file.read_text(encoding="utf-8"),
                    )

    async def close(self) -> None:
        """Close all workspaces."""
        self._agent_workspaces.clear()
        self._stable = None
```

**`_safe_id()`** converts a node_id like `"src/auth.py::validate_token"` to a
filesystem-safe string for the workspace directory name. Use a hash or
simple character replacement.

---

## 12. core/grail.py — Tool Loading

### What it does

Discovers `.pym` Grail scripts from an agent's workspace `_bundle/tools/` directory,
wraps each one as a tool object that the LLM kernel can call.

### Implementation

```python
"""Grail tool integration for agent workspaces."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import grail
from structured_agents.types import ToolCall, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


def _build_parameters(script: grail.GrailScript) -> dict[str, Any]:
    """Build JSON Schema parameters from a Grail script's Input() declarations."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    type_map = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}

    for name, spec in script.inputs.items():
        properties[name] = {"type": type_map.get(spec.type_annotation, "string")}
        if spec.required:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class GrailTool:
    """A tool backed by a .pym script with externals and virtual FS."""

    def __init__(
        self,
        script: grail.GrailScript,
        *,
        externals: dict[str, Any],
        name_override: str | None = None,
    ):
        self._script = script
        self._externals = externals
        self._schema = ToolSchema(
            name=name_override or getattr(script, "name", "grail_tool"),
            description=script.__doc__ or f"Tool: {script.name}",
            parameters=_build_parameters(script),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        try:
            # Only pass externals that the script actually declares
            used_externals = {
                name: fn for name, fn in self._externals.items()
                if name in self._script.externals
            }
            result = await self._script.run(
                inputs=arguments,
                externals=used_externals,
            )
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(call_id=call_id, name=self._schema.name, output=output, is_error=False)
        except Exception as exc:
            return ToolResult(call_id=call_id, name=self._schema.name, output=str(exc), is_error=True)


async def discover_tools(
    workspace: AgentWorkspace,
    externals: dict[str, Any],
) -> list[GrailTool]:
    """Discover and load .pym tools from an agent's _bundle/tools/ directory.

    Reads tool scripts from the workspace (not the filesystem), loads each
    one via grail.load(), and wraps them as GrailTool instances.
    """
    tools: list[GrailTool] = []

    try:
        tool_files = await workspace.list_dir("_bundle/tools")
    except FileNotFoundError:
        return tools

    for filename in tool_files:
        if not filename.endswith(".pym"):
            continue
        try:
            source = await workspace.read(f"_bundle/tools/{filename}")
            # grail.load() can load from a string with a name
            script = grail.loads(source, name=filename.removesuffix(".pym"))
            tools.append(GrailTool(script=script, externals=externals))
            logger.debug("Loaded tool: %s", filename)
        except Exception as exc:
            logger.warning("Failed to load tool %s: %s", filename, exc)

    return tools
```

### Key design choice: load from workspace, not filesystem

Tools are read from the agent's Cairn workspace via `workspace.read()`, not from
disk. This means:
- An agent can create/modify its own tools (they're just workspace files)
- Tool discovery is unified — no special handling for "system tools" vs
  "user tools" vs "agent-created tools"
- Tools are isolated per agent (one agent's tool changes don't affect another)

---

## 13. core/runner.py — The Agent Runner

### What it does

The runner is the heart of Remora. It:
1. Consumes triggers from the EventStore's trigger queue
2. For each trigger, loads the agent's node, workspace, bundle config, and tools
3. Builds the externals dict
4. Creates an LLM kernel and runs a turn
5. Emits result events

### Implementation

```python
"""The agent runner — single execution path for all agent turns."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import yaml
from structured_agents import Message

from remora.core.config import Config
from remora.core.events import Event, EventStore, AgentStartEvent, AgentCompleteEvent, AgentErrorEvent
from remora.core.graph import NodeStore
from remora.core.grail import discover_tools
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.workspace import CairnWorkspaceService

logger = logging.getLogger(__name__)


@dataclass
class Trigger:
    """A trigger waiting to be executed."""
    node_id: str
    correlation_id: str
    event: Event | None = None


class AgentRunner:
    """Unified agent execution coordinator.

    One runner handles all modes: CLI, web, LSP. It consumes triggers
    from the EventStore and runs agent turns.
    """

    def __init__(
        self,
        event_store: EventStore,
        node_store: NodeStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
    ):
        self._event_store = event_store
        self._node_store = node_store
        self._workspace_service = workspace_service
        self._config = config
        self._running = False
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

        # Cascade prevention
        self._cooldowns: dict[str, float] = {}      # node_id → last trigger time (ms)
        self._depths: dict[str, int] = {}            # "node:corr" → current depth

    async def run_forever(self) -> None:
        """Main loop: consume triggers from EventStore, execute turns."""
        self._running = True
        logger.info("AgentRunner started, waiting for triggers")
        try:
            async for node_id, event in self._event_store.get_triggers():
                if not self._running:
                    break
                correlation_id = getattr(event, "correlation_id", None) or str(uuid.uuid4())
                await self.trigger(node_id, correlation_id, event)
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def trigger(
        self, node_id: str, correlation_id: str, event: Event | None = None
    ) -> None:
        """Enqueue a trigger with cooldown + depth checks."""
        # Cooldown check
        now_ms = time.time() * 1000
        last = self._cooldowns.get(node_id, 0)
        if now_ms - last < self._config.trigger_cooldown_ms:
            logger.debug("Cooldown active for %s, skipping", node_id)
            return
        self._cooldowns[node_id] = now_ms

        # Depth check
        depth_key = f"{node_id}:{correlation_id}"
        depth = self._depths.get(depth_key, 0)
        if depth >= self._config.max_trigger_depth:
            logger.warning("Depth limit for %s, skipping", node_id)
            await self._event_store.append(
                AgentErrorEvent(agent_id=node_id, error="Cascade depth limit exceeded")
            )
            return

        # Execute in background with semaphore
        self._depths[depth_key] = depth + 1
        asyncio.create_task(
            self._execute_turn(Trigger(node_id, correlation_id, event))
        )

    async def _execute_turn(self, trigger: Trigger) -> None:
        """Execute a single agent turn."""
        node_id = trigger.node_id
        depth_key = f"{node_id}:{trigger.correlation_id}"

        async with self._semaphore:
            try:
                # 1. Load node
                node = await self._node_store.get_node(node_id)
                if not node:
                    logger.error("Node %s not found", node_id)
                    return

                # 2. Set status to running
                await self._node_store.set_status(node_id, "running")
                await self._event_store.append(
                    AgentStartEvent(agent_id=node_id, node_name=node.name)
                )

                # 3. Get workspace
                workspace = await self._workspace_service.get_agent_workspace(node_id)

                # 4. Read bundle config from workspace
                try:
                    bundle_yaml = await workspace.read("_bundle/bundle.yaml")
                    bundle_config = yaml.safe_load(bundle_yaml) or {}
                except FileNotFoundError:
                    bundle_config = {}

                system_prompt = bundle_config.get("system_prompt", "You are an autonomous code agent.")
                model_name = bundle_config.get("model", self._config.model_default)
                max_turns = bundle_config.get("max_turns", self._config.max_turns)

                # 5. Build externals
                externals = self._build_externals(node_id, workspace, trigger.correlation_id)

                # 6. Discover tools from workspace
                tools = await discover_tools(workspace, externals)

                # 7. Build messages
                messages = [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=self._build_prompt(node, trigger)),
                ]

                # 8. Create kernel and run
                kernel = create_kernel(
                    model_name=model_name,
                    base_url=self._config.model_base_url,
                    api_key=self._config.model_api_key,
                    timeout=self._config.timeout_s,
                    tools=tools,
                )
                try:
                    tool_schemas = [tool.schema for tool in tools]
                    result = await kernel.run(messages, tool_schemas, max_turns=max_turns)
                finally:
                    await kernel.close()

                # 9. Emit completion
                response_text = extract_response_text(result)
                await self._event_store.append(
                    AgentCompleteEvent(
                        agent_id=node_id,
                        result_summary=response_text[:200],
                        correlation_id=trigger.correlation_id,
                    )
                )

            except Exception as exc:
                logger.exception("Turn failed for %s", node_id)
                await self._event_store.append(
                    AgentErrorEvent(agent_id=node_id, error=str(exc))
                )
            finally:
                await self._node_store.set_status(node_id, "idle")
                # Decrement depth
                self._depths[depth_key] = self._depths.get(depth_key, 1) - 1
                if self._depths[depth_key] <= 0:
                    self._depths.pop(depth_key, None)

    def _build_prompt(self, node: CodeNode, trigger: Trigger) -> str:
        """Build the user-turn prompt from node identity + trigger event."""
        parts = [
            f"# Node: {node.full_name}",
            f"Type: {node.node_type} | File: {node.file_path}:{node.start_line}-{node.end_line}",
            f"\n## Source Code\n```\n{node.source_code}\n```",
        ]
        if trigger.event:
            parts.append(f"\n## Trigger\nEvent: {trigger.event.event_type}")
            content = getattr(trigger.event, "content", None) or getattr(trigger.event, "message", None)
            if content:
                parts.append(f"Content: {content}")
        return "\n".join(parts)

    def _build_externals(
        self, node_id: str, workspace: AgentWorkspace, correlation_id: str | None
    ) -> dict[str, Any]:
        """Build the complete externals dict for .pym tools.

        This is the ENTIRE API surface between Python and Grail scripts.
        See Section 14 for the full contract.
        """
        # (Implementation detailed in Section 14)
        ...
```

### How it all connects

The runner doesn't know about LSP, CLI, or web. It just:
1. Listens for triggers (from EventStore)
2. Runs turns (node → workspace → tools → kernel)
3. Emits events (back to EventStore)

All surfaces (web, CLI, LSP) interact with the system by appending events to
EventStore. The subscription system routes them to the right agents.

---

## 14. The Externals Contract

### What it is

The externals dict is the **complete API** between the Python substrate and
`.pym` Grail tools. Every external is an async function that the tool can call.

### Implementation in `_build_externals()`

```python
def _build_externals(
    self, node_id: str, workspace: AgentWorkspace, correlation_id: str | None
) -> dict[str, Any]:
    """Build the full externals dict."""

    # --- Workspace operations (from Cairn) ---

    async def read_file(path: str) -> str:
        return await workspace.read(path)

    async def write_file(path: str, content: str) -> bool:
        await workspace.write(path, content)
        return True

    async def list_dir(path: str = ".") -> list[str]:
        return await workspace.list_dir(path)

    async def file_exists(path: str) -> bool:
        return await workspace.exists(path)

    async def search_files(pattern: str) -> list[str]:
        # Delegate to Cairn's search or implement glob over workspace
        entries = await workspace.list_dir(".")
        return [e for e in entries if pattern in e]

    # --- Graph operations ---

    async def graph_get_node(target_id: str) -> dict:
        node = await self._node_store.get_node(target_id)
        return node.model_dump() if node else {}

    async def graph_query_nodes(
        node_type: str | None = None, status: str | None = None
    ) -> list[dict]:
        nodes = await self._node_store.list_nodes(node_type=node_type, status=status)
        return [n.model_dump() for n in nodes]

    async def graph_get_edges(target_id: str) -> list[dict]:
        edges = await self._node_store.get_edges(target_id)
        return [{"from_id": e.from_id, "to_id": e.to_id, "edge_type": e.edge_type} for e in edges]

    async def graph_set_status(target_id: str, new_status: str) -> bool:
        await self._node_store.set_status(target_id, new_status)
        return True

    # --- Event operations ---

    async def event_emit(event_type: str, payload: dict) -> bool:
        event = Event(event_type=event_type, correlation_id=correlation_id, **payload)
        await self._event_store.append(event)
        return True

    async def event_subscribe(
        event_types: list[str] | None = None,
        from_agents: list[str] | None = None,
        path_glob: str | None = None,
    ) -> int:
        from remora.core.events import SubscriptionPattern
        pattern = SubscriptionPattern(
            event_types=event_types, from_agents=from_agents, path_glob=path_glob
        )
        sub_id = await self._event_store.subscriptions.register(node_id, pattern)
        return sub_id

    async def event_unsubscribe(subscription_id: int) -> bool:
        return await self._event_store.subscriptions.unregister(subscription_id)

    async def event_get_history(target_id: str, limit: int = 20) -> list[dict]:
        return await self._event_store.get_events_for_agent(target_id, limit=limit)

    # --- Communication ---

    async def send_message(to_node_id: str, content: str) -> bool:
        from remora.core.events import AgentMessageEvent
        event = AgentMessageEvent(
            from_agent=node_id, to_agent=to_node_id, content=content,
            correlation_id=correlation_id,
        )
        await self._event_store.append(event)
        return True

    async def broadcast(pattern: str, content: str) -> str:
        from remora.core.events import AgentMessageEvent
        nodes = await self._node_store.list_nodes()
        targets = _resolve_broadcast_targets(node_id, pattern, nodes)
        for target_id in targets:
            event = AgentMessageEvent(
                from_agent=node_id, to_agent=target_id, content=content,
                correlation_id=correlation_id,
            )
            await self._event_store.append(event)
        return f"Broadcast sent to {len(targets)} agents"

    # --- Code operations ---

    async def propose_rewrite(new_source: str) -> str:
        proposal_id = str(uuid.uuid4())[:8]
        from remora.core.events import RewriteProposalEvent
        node = await self._node_store.get_node(node_id)
        if not node:
            return "Error: node not found"
        await self._event_store.append(RewriteProposalEvent(
            agent_id=node_id,
            proposal_id=proposal_id,
            file_path=node.file_path,
            old_source=node.source_code,
            new_source=new_source,
            correlation_id=correlation_id,
        ))
        await self._node_store.set_status(node_id, "pending_approval")
        return proposal_id

    async def get_node_source(target_id: str) -> str:
        node = await self._node_store.get_node(target_id)
        return node.source_code if node else ""

    # --- Assemble ---

    return {
        # Workspace
        "read_file": read_file,
        "write_file": write_file,
        "list_dir": list_dir,
        "file_exists": file_exists,
        "search_files": search_files,
        # Graph
        "graph_get_node": graph_get_node,
        "graph_query_nodes": graph_query_nodes,
        "graph_get_edges": graph_get_edges,
        "graph_set_status": graph_set_status,
        # Events
        "event_emit": event_emit,
        "event_subscribe": event_subscribe,
        "event_unsubscribe": event_unsubscribe,
        "event_get_history": event_get_history,
        # Communication
        "send_message": send_message,
        "broadcast": broadcast,
        # Code
        "propose_rewrite": propose_rewrite,
        "get_node_source": get_node_source,
        # Identity (constants, not functions)
        "my_node_id": node_id,
        "my_correlation_id": correlation_id,
    }
```

### How a .pym tool uses externals

A `.pym` tool declares `@external` for each function it needs:

```python
# send_message.pym
Input("to_node_id", type=str, required=True)
Input("content", type=str, required=True)

@external
async def send_message(to_node_id: str, content: str) -> bool: ...

result = await send_message(to_node_id, content)
return f"Message sent: {result}"
```

When this tool runs, Grail matches `send_message` in the script's `@external`
declarations to the `send_message` key in the externals dict. The Python
closure executes and returns the result to the script.

---

## Part III: Code Plugin (Phase 4)

---

## 15. code/discovery.py — Tree-Sitter Scanning

### What it does

Parses source files using tree-sitter and produces `CSTNode` objects — immutable
data representations of code elements (functions, classes, methods, files).

### 15.1 CSTNode model

```python
"""Tree-sitter code discovery."""
from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CSTNode(BaseModel):
    """An immutable code element discovered from source."""

    model_config = ConfigDict(frozen=True)

    node_id: str        # "file_path::full_name"
    node_type: str      # "function", "class", "method", "file"
    name: str           # "validate_token"
    full_name: str      # "AuthService.validate_token"
    file_path: str
    text: str           # source code of this element
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    parent_id: str | None = None
```

### 15.2 Discovery function

The `discover()` function walks a directory tree, finds source files, parses
each one with tree-sitter, and yields `CSTNode` objects.

```python
import tree_sitter
from concurrent.futures import ThreadPoolExecutor


def discover(
    paths: list[Path],
    *,
    languages: list[str] | None = None,
    ignore_patterns: tuple[str, ...] = (),
) -> list[CSTNode]:
    """Discover all code nodes in the given paths.

    Uses tree-sitter to parse source files and extract functions,
    classes, methods. Returns a flat list of CSTNode objects.
    """
    nodes: list[CSTNode] = []
    for source_file in _walk_source_files(paths, ignore_patterns):
        lang = _detect_language(source_file)
        if languages and lang not in languages:
            continue
        if lang is None:
            continue
        file_nodes = _parse_file(source_file, lang)
        nodes.extend(file_nodes)
    return nodes
```

### 15.3 How tree-sitter parsing works

For each source file:

1. **Detect language** from file extension (`.py` → Python, `.js` → JavaScript)
2. **Load the grammar** — tree-sitter uses pre-compiled grammar libraries
3. **Parse the file** → get a syntax tree
4. **Run queries** — tree-sitter queries find functions, classes, methods
5. **Extract CSTNodes** — for each match, build a `CSTNode` with the name,
   type, location, and source text

```python
def _parse_file(path: Path, language: str) -> list[CSTNode]:
    """Parse a single file and return its CSTNodes."""
    source = path.read_bytes()
    parser = _get_parser(language)
    tree = parser.parse(source)

    nodes: list[CSTNode] = []
    query = _get_query(language)
    cursor = tree_sitter.QueryCursor(query)
    cursor.execute(tree.root_node)

    for match in cursor.matches():
        # Extract name, type, range from the match
        node_type, name, full_name, start, end = _extract_match(match, path)
        text = source[start.byte:end.byte].decode("utf-8", errors="replace")
        node_id = f"{path}::{full_name}"

        nodes.append(CSTNode(
            node_id=node_id,
            node_type=node_type,
            name=name,
            full_name=full_name,
            file_path=str(path),
            text=text,
            start_line=start.row + 1,
            end_line=end.row + 1,
            start_byte=start.byte,
            end_byte=end.byte,
        ))

    return nodes
```

### 15.4 Tree-sitter queries

Queries are S-expression patterns that match syntax tree structures. Store them
as files per language:

```
# queries/python.scm
(function_definition
  name: (identifier) @name) @function

(class_definition
  name: (identifier) @name
  body: (block) @body) @class
```

Load them at startup and cache per language.

### Testing

```python
def test_discover_python_function(tmp_path):
    source = tmp_path / "example.py"
    source.write_text("def greet(name):\n    return f'Hello {name}'\n")
    nodes = discover([tmp_path])
    assert len(nodes) >= 1
    func = [n for n in nodes if n.name == "greet"][0]
    assert func.node_type == "function"
    assert func.start_line == 1
    assert func.end_line == 2
```

---

## 16. code/projections.py — CSTNode to CodeNode

### What it does

Takes `CSTNode` objects from discovery and converts them into `CodeNode` objects
that get stored in the graph. Also handles provisioning the agent's workspace
with a template bundle.

### Implementation

```python
"""Project CSTNodes into CodeNodes and provision workspaces."""
from __future__ import annotations

import hashlib
from pathlib import Path

from remora.core.config import Config
from remora.core.node import CodeNode
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService
from remora.code.discovery import CSTNode


async def project_nodes(
    cst_nodes: list[CSTNode],
    node_store: NodeStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
) -> list[CodeNode]:
    """Convert CSTNodes to CodeNodes, upsert into graph, provision workspaces.

    For each CSTNode:
    1. Check if a CodeNode already exists in the store
    2. If new: create CodeNode, provision workspace with template bundle
    3. If changed (source_hash differs): update the CodeNode
    4. If unchanged: skip
    """
    results: list[CodeNode] = []
    bundle_root = Path(config.bundle_root)

    for cst in cst_nodes:
        source_hash = hashlib.sha256(cst.text.encode()).hexdigest()

        existing = await node_store.get_node(cst.node_id)
        if existing and existing.source_hash == source_hash:
            results.append(existing)
            continue

        code_node = CodeNode(
            node_id=cst.node_id,
            node_type=cst.node_type,
            name=cst.name,
            full_name=cst.full_name,
            file_path=cst.file_path,
            start_line=cst.start_line,
            end_line=cst.end_line,
            start_byte=cst.start_byte,
            end_byte=cst.end_byte,
            source_code=cst.text,
            source_hash=source_hash,
            parent_id=cst.parent_id,
            bundle_name=config.bundle_mapping.get(cst.node_type),
        )

        await node_store.upsert_node(code_node)

        # Provision workspace for new nodes only
        if existing is None:
            template_dirs = [bundle_root / "system"]
            bundle_name = config.bundle_mapping.get(cst.node_type)
            if bundle_name:
                template_dirs.append(bundle_root / bundle_name)
            await workspace_service.provision_bundle(cst.node_id, template_dirs)

        results.append(code_node)

    return results
```

### The provisioning flow

When a node is **first discovered** (no existing entry in NodeStore):

```
CSTNode discovered → CodeNode created → NodeStore.upsert_node()
                                       → workspace_service.provision_bundle()
                                           ├─ copy bundles/system/tools/*.pym → _bundle/tools/
                                           ├─ copy bundles/code-agent/tools/*.pym → _bundle/tools/
                                           └─ copy bundles/code-agent/bundle.yaml → _bundle/bundle.yaml
```

When a node's **source code changes** (hash differs):

```
CSTNode rediscovered → CodeNode updated → NodeStore.upsert_node()
                                         (workspace NOT re-provisioned — agent keeps its config)
```

This is important: **re-provisioning would overwrite any customizations the
agent made to its own bundle.** Once provisioned, the agent owns its workspace.

---

## 17. code/reconciler.py — File Watching

### What it does

The reconciler runs at startup and optionally watches for file changes. It
bridges the gap between the filesystem and the graph:

1. **Initial scan**: discover all code nodes → project into graph
2. **Ongoing watch**: detect file changes → re-discover affected files → update graph
3. **Emit events**: `NodeDiscoveredEvent` for new nodes, `NodeChangedEvent` for
   changes, `ContentChangedEvent` for file-level changes

### Implementation

```python
"""File reconciler — keeps the graph in sync with source code."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from remora.core.config import Config
from remora.core.events import EventStore, NodeDiscoveredEvent, NodeChangedEvent, ContentChangedEvent
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService
from remora.code.discovery import discover, CSTNode
from remora.code.projections import project_nodes

logger = logging.getLogger(__name__)


async def reconcile_on_startup(
    config: Config,
    node_store: NodeStore,
    event_store: EventStore,
    workspace_service: CairnWorkspaceService,
    project_root: Path,
) -> list:
    """Run initial discovery and project all nodes."""
    discovery_paths = [project_root / p for p in config.discovery_paths]
    cst_nodes = discover(
        discovery_paths,
        languages=list(config.discovery_languages) if config.discovery_languages else None,
        ignore_patterns=config.workspace_ignore_patterns,
    )
    logger.info("Discovered %d code nodes", len(cst_nodes))

    code_nodes = await project_nodes(
        cst_nodes, node_store, workspace_service, config
    )

    # Register default subscriptions for each node
    for node in code_nodes:
        from remora.core.events import SubscriptionPattern
        # Each agent subscribes to messages sent directly to it
        await event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(to_agent=node.node_id),
        )
        # And to changes in its own file
        await event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(
                event_types=["ContentChangedEvent"],
                path_glob=node.file_path,
            ),
        )

    # Emit discovery events
    for node in code_nodes:
        await event_store.append(NodeDiscoveredEvent(
            node_id=node.node_id,
            node_type=node.node_type,
            file_path=node.file_path,
            name=node.name,
        ))

    return code_nodes
```

### File watching (optional, for development)

For ongoing file watching, use `watchfiles` or a simple polling loop:

```python
async def watch_and_reconcile(
    config: Config,
    node_store: NodeStore,
    event_store: EventStore,
    workspace_service: CairnWorkspaceService,
    project_root: Path,
) -> None:
    """Watch for file changes and re-reconcile affected files."""
    # Use watchfiles or polling to detect changes
    # When a file changes:
    #   1. Re-discover just that file
    #   2. Project changed nodes
    #   3. Emit ContentChangedEvent
    ...
```

---

## Part IV: Tool Bundles (Phase 2–4)

---

## 18. Writing .pym Tools

### What is a .pym file?

A `.pym` file is a Grail script — a sandboxed Python-like scripting language.
It looks like Python but runs in a restricted environment. The key features:

- **`Input("name", type=str)`** — declares a typed parameter that the LLM provides
- **`@external async def func(...)`** — declares a function provided by the host
- **Regular Python logic** — the body runs, calls externals, returns a result
- **The return value** is sent back to the LLM as the tool's output

### Anatomy of a .pym tool

```python
# Example: send_message.pym
"""Send a direct message from this agent to another agent."""

# Inputs — these become the tool's JSON Schema parameters.
# The LLM provides these values when calling the tool.
Input("to_node_id", type=str, required=True)
Input("content", type=str, required=True)

# Externals — these are provided by Remora's externals dict.
# The @external decorator tells Grail to look for these in the externals.
@external
async def send_message(to_node_id: str, content: str) -> bool: ...

# Body — runs when the tool is called.
result = await send_message(to_node_id, content)
return f"Message sent to {to_node_id}: {result}"
```

### How the LLM sees it

The `.pym` script above becomes a tool with this JSON Schema:

```json
{
  "name": "send_message",
  "description": "Send a direct message from this agent to another agent.",
  "parameters": {
    "type": "object",
    "properties": {
      "to_node_id": {"type": "string"},
      "content": {"type": "string"}
    },
    "required": ["to_node_id", "content"]
  }
}
```

The LLM sees this schema, decides to call the tool, provides the arguments,
and Grail executes the script with those arguments.

---

## 19. System Tools

These ship with every agent. They provide the basic swarm capabilities.

### send_message.pym

```python
"""Send a direct message to another agent in the swarm."""
Input("to_node_id", type=str, required=True)
Input("content", type=str, required=True)

@external
async def send_message(to_node_id: str, content: str) -> bool: ...

result = await send_message(to_node_id, content)
return f"Message sent to {to_node_id}"
```

### subscribe.pym

```python
"""Subscribe to additional event patterns."""
Input("event_types", type=str, required=False)   # comma-separated
Input("from_agents", type=str, required=False)    # comma-separated
Input("path_glob", type=str, required=False)

@external
async def event_subscribe(event_types, from_agents, path_glob) -> int: ...

et = event_types.split(",") if event_types else None
fa = from_agents.split(",") if from_agents else None
sub_id = await event_subscribe(et, fa, path_glob)
return f"Subscription {sub_id} registered"
```

### unsubscribe.pym

```python
"""Remove a subscription by ID."""
Input("subscription_id", type=int, required=True)

@external
async def event_unsubscribe(subscription_id: int) -> bool: ...

result = await event_unsubscribe(subscription_id)
return f"Unsubscribed: {result}"
```

### broadcast.pym

```python
"""Broadcast a message to multiple agents using a pattern."""
Input("pattern", type=str, required=True)    # "children", "siblings", "file:path"
Input("content", type=str, required=True)

@external
async def broadcast(pattern: str, content: str) -> str: ...

result = await broadcast(pattern, content)
return result
```

### query_agents.pym

```python
"""List agents in the swarm, optionally filtered by type."""
Input("node_type", type=str, required=False)

@external
async def graph_query_nodes(node_type, status) -> list: ...

import json
agents = await graph_query_nodes(node_type, None)
return json.dumps(agents, indent=2)
```

---

## 20. Code Tools

These ship with the `code-agent` bundle. They provide code-specific capabilities.

### rewrite_self.pym

```python
"""Propose a rewrite of this agent's own source code."""
Input("new_source", type=str, required=True)

@external
async def propose_rewrite(new_source: str) -> str: ...

proposal_id = await propose_rewrite(new_source)
return f"Rewrite proposal created: {proposal_id}. Awaiting human approval."
```

### scaffold.pym

```python
"""Request scaffolding of a new code element."""
Input("intent", type=str, required=True)
Input("element_type", type=str, required=False)  # "function", "class", etc.

@external
async def event_emit(event_type: str, payload: dict) -> bool: ...
@external
my_node_id: str

await event_emit("ScaffoldRequestEvent", {
    "agent_id": my_node_id,
    "intent": intent,
    "element_type": element_type or "function",
})
return f"Scaffold request submitted: {intent}"
```

---

## 21. Companion Tools

These ship with the `companion` bundle. They help agents maintain awareness
of their own state and relationships.

### summarize.pym

```python
"""Summarize recent activity and write to workspace notes."""
@external
async def read_file(path: str) -> str: ...
@external
async def write_file(path: str, content: str) -> bool: ...
@external
async def event_get_history(node_id: str, limit: int) -> list: ...
@external
my_node_id: str

import json
history = await event_get_history(my_node_id, 10)
summary_lines = []
for event in history:
    summary_lines.append(f"- {event.get('event_type', '?')}: {event.get('summary', '')}")

summary = "# Recent Activity Summary\n\n" + "\n".join(summary_lines)
await write_file("notes/summary.md", summary)
return "Summary updated"
```

### categorize.pym

```python
"""Categorize this node based on its source code."""
@external
async def read_file(path: str) -> str: ...
@external
async def write_file(path: str, content: str) -> bool: ...
@external
async def graph_get_node(node_id: str) -> dict: ...
@external
my_node_id: str

node = await graph_get_node(my_node_id)
source = node.get("source_code", "")
node_type = node.get("node_type", "unknown")

# The LLM will be analyzing this as part of the tool call context
# Write initial categorization metadata
meta = f"# Categories\n\nType: {node_type}\nAnalysis pending...\n"
await write_file("meta/categories.md", meta)
return f"Categorization initialized for {node_type} node"
```

### find_links.pym

```python
"""Find related nodes and record links."""
@external
async def graph_get_node(node_id: str) -> dict: ...
@external
async def graph_query_nodes(node_type, status) -> list: ...
@external
async def write_file(path: str, content: str) -> bool: ...
@external
my_node_id: str

import json
node = await graph_get_node(my_node_id)
callee_ids = node.get("callee_ids", [])
caller_ids = node.get("caller_ids", [])

links = []
for cid in callee_ids:
    links.append(f"- Calls: `{cid}`")
for cid in caller_ids:
    links.append(f"- Called by: `{cid}`")

content = "# Links\n\n" + "\n".join(links) if links else "# Links\n\nNo links found."
await write_file("meta/links.md", content)
return f"Found {len(links)} links"
```

### reflect.pym

```python
"""Reflect on recent interactions and write observations."""
@external
async def read_file(path: str) -> str: ...
@external
async def write_file(path: str, content: str) -> bool: ...
@external
async def event_get_history(node_id: str, limit: int) -> list: ...
@external
my_node_id: str

import json
history = await event_get_history(my_node_id, 20)

# Read existing notes
try:
    existing = await read_file("notes/reflection.md")
except:
    existing = ""

# Append new reflection entry
import time
timestamp = time.strftime("%Y-%m-%d %H:%M")
entry = f"\n---\n## {timestamp}\n\nReviewed {len(history)} recent events.\n"
await write_file("notes/reflection.md", existing + entry)
return "Reflection recorded"
```

---

## 22. Template Bundles

### bundle.yaml format

Each template bundle has a `bundle.yaml` that configures the agent's behavior:

```yaml
# bundles/code-agent/bundle.yaml
name: code-agent
system_prompt: |
  You are an autonomous AI agent embodying a code element.
  You have access to your own source code and can propose rewrites.

  # Core Rules
  1. You may ONLY modify your own code using rewrite_self.
  2. To request changes elsewhere, use send_message.
  3. All rewrites are proposals — a human must approve them.

  # Your Identity
  Your node ID, type, file path, and source code will be provided
  in the user prompt for each turn.

model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"
max_turns: 8
```

```yaml
# bundles/system/bundle.yaml
name: system
system_prompt: |
  You are a helpful assistant with access to swarm communication tools.
model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"
max_turns: 4
```

### Template directory structure

```
bundles/
  system/                    # Merged into EVERY agent
    bundle.yaml              # (overridden by type-specific bundle.yaml)
    tools/
      send_message.pym
      subscribe.pym
      unsubscribe.pym
      broadcast.pym
      query_agents.pym
  code-agent/                # For function/class/method/file nodes
    bundle.yaml
    tools/
      rewrite_self.pym
      scaffold.pym
  companion/                 # For companion-enhanced agents
    bundle.yaml
    tools/
      summarize.pym
      categorize.pym
      find_links.pym
      reflect.pym
```

### How template layering works during provisioning

When `workspace_service.provision_bundle()` is called:

```python
template_dirs = [
    bundle_root / "system",       # base tools for all agents
    bundle_root / "code-agent",   # type-specific tools + config
]
```

1. System tools are copied first: `_bundle/tools/send_message.pym`, etc.
2. Type-specific tools are copied next: `_bundle/tools/rewrite_self.pym`, etc.
3. Type-specific `bundle.yaml` **overwrites** the system `bundle.yaml`

The result is one flat `_bundle/` directory with all tools merged and the
type-specific config.

---

## Part V: Surfaces (Phase 5–6)

---

## 23. web/server.py — HTTP + SSE

### What it does

A Starlette web server that provides:
- **SSE endpoint** — streams all events in real time to the browser
- **REST API** — graph queries, node details, chat, proposal review
- **Static files** — serves the graph visualization HTML/JS

### Implementation sketch

```python
"""Remora web server with SSE event streaming."""
from __future__ import annotations

import asyncio
import json

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from sse_starlette.sse import EventSourceResponse


def create_app(event_store, node_store, event_bus, runner) -> Starlette:
    """Create the Starlette application."""

    async def index(request: Request) -> HTMLResponse:
        """Serve the graph visualization page."""
        return HTMLResponse(GRAPH_HTML)

    async def api_nodes(request: Request) -> JSONResponse:
        """List all nodes."""
        nodes = await node_store.list_nodes()
        return JSONResponse([n.model_dump() for n in nodes])

    async def api_node(request: Request) -> JSONResponse:
        """Get a single node."""
        node_id = request.path_params["node_id"]
        node = await node_store.get_node(node_id)
        if not node:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(node.model_dump())

    async def api_edges(request: Request) -> JSONResponse:
        """Get edges for a node."""
        node_id = request.path_params["node_id"]
        edges = await node_store.get_edges(node_id)
        return JSONResponse([{"from": e.from_id, "to": e.to_id, "type": e.edge_type} for e in edges])

    async def api_chat(request: Request) -> JSONResponse:
        """Send a chat message to an agent."""
        data = await request.json()
        node_id = data["node_id"]
        message = data["message"]
        from remora.core.events import HumanChatEvent
        event = HumanChatEvent(to_agent=node_id, message=message)
        await event_store.append(event)
        return JSONResponse({"status": "sent"})

    async def api_events(request: Request) -> JSONResponse:
        """Get recent events."""
        limit = int(request.query_params.get("limit", "50"))
        events = await event_store.get_events(limit=limit)
        return JSONResponse(events)

    async def sse_stream(request: Request) -> EventSourceResponse:
        """SSE endpoint — streams all events in real time."""
        async def event_generator():
            async with event_bus.stream() as events:
                async for event in events:
                    yield {
                        "event": event.event_type,
                        "data": json.dumps(event.model_dump()),
                    }
        return EventSourceResponse(event_generator())

    routes = [
        Route("/", index),
        Route("/api/nodes", api_nodes),
        Route("/api/nodes/{node_id:path}", api_node),
        Route("/api/nodes/{node_id:path}/edges", api_edges),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/events", api_events),
        Route("/sse", sse_stream),
    ]

    return Starlette(routes=routes)
```

### Running the web server

```python
import uvicorn

app = create_app(event_store, node_store, event_bus, runner)
uvicorn.run(app, host="127.0.0.1", port=8080)
```

---

## 24. web/views.py — Graph Visualization

### What it does

Provides the HTML + JavaScript for the real-time graph visualization. The
browser connects to the SSE endpoint and updates the graph as events arrive.

### Technology choice

For large graphs, use **Sigma.js** with **graphology** — it uses WebGL for
rendering and can handle thousands of nodes smoothly. Alternatives:
- **Cytoscape.js** — more features, but slower for very large graphs
- **d3-force** — very flexible, but CPU-based (SVG), struggles above ~500 nodes

### HTML structure

```html
<!-- Served as a string from web/views.py -->
<!DOCTYPE html>
<html>
<head>
    <title>Remora — Agent Graph</title>
    <script src="https://unpkg.com/graphology/dist/graphology.umd.min.js"></script>
    <script src="https://unpkg.com/sigma/build/sigma.min.js"></script>
    <style>
        body { margin: 0; display: flex; height: 100vh; }
        #graph { flex: 1; }
        #sidebar { width: 400px; overflow-y: auto; border-left: 1px solid #ccc; padding: 16px; }
        .node-idle { }
        .node-running { animation: pulse 1s infinite; }
    </style>
</head>
<body>
    <div id="graph"></div>
    <div id="sidebar">
        <h2 id="node-name">Select a node</h2>
        <div id="node-details"></div>
        <div id="chat-panel" style="display:none">
            <textarea id="chat-input"></textarea>
            <button onclick="sendChat()">Send</button>
            <div id="chat-history"></div>
        </div>
    </div>
    <script>
        // Initialize graph
        const graph = new graphology.Graph();
        const container = document.getElementById('graph');
        const renderer = new Sigma(graph, container);

        // SSE connection
        const evtSource = new EventSource('/sse');
        evtSource.addEventListener('NodeDiscoveredEvent', (e) => {
            const data = JSON.parse(e.data);
            if (!graph.hasNode(data.node_id)) {
                graph.addNode(data.node_id, {
                    label: data.name,
                    x: Math.random(), y: Math.random(),
                    size: 5,
                    color: '#4a9eff',
                });
            }
        });
        evtSource.addEventListener('AgentStartEvent', (e) => {
            const data = JSON.parse(e.data);
            if (graph.hasNode(data.agent_id)) {
                graph.setNodeAttribute(data.agent_id, 'color', '#ff9800');
            }
        });
        evtSource.addEventListener('AgentCompleteEvent', (e) => {
            const data = JSON.parse(e.data);
            if (graph.hasNode(data.agent_id)) {
                graph.setNodeAttribute(data.agent_id, 'color', '#4caf50');
                setTimeout(() => {
                    graph.setNodeAttribute(data.agent_id, 'color', '#4a9eff');
                }, 2000);
            }
        });

        // Click handler — show node details in sidebar
        renderer.on('clickNode', async ({ node }) => {
            const resp = await fetch(`/api/nodes/${encodeURIComponent(node)}`);
            const data = await resp.json();
            document.getElementById('node-name').textContent = data.full_name;
            document.getElementById('node-details').innerHTML = `
                <p><strong>Type:</strong> ${data.node_type}</p>
                <p><strong>File:</strong> ${data.file_path}:${data.start_line}</p>
                <p><strong>Status:</strong> ${data.status}</p>
                <pre>${data.source_code}</pre>
            `;
            document.getElementById('chat-panel').style.display = 'block';
            window._selectedNode = node;
        });

        async function sendChat() {
            const input = document.getElementById('chat-input');
            await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({node_id: window._selectedNode, message: input.value}),
            });
            input.value = '';
        }
    </script>
</body>
</html>
```

This is a starting point. In production you'd want:
- Force-directed layout (graphology has `graphology-layout-forceatlas2`)
- Node coloring by type (function=blue, class=purple, method=green)
- Edge rendering (parent→child, caller→callee)
- Event stream panel showing recent events
- Proposal review panel

---

## 25. lsp/server.py — LSP Adapter

### What it does

Optional thin adapter that connects Neovim (or any LSP client) to Remora.
Translates LSP protocol events into Remora events and renders CodeNode data
as LSP responses.

### Capabilities

- **Code Lens**: Show agent status on each function/class (idle/running/error)
- **Hover**: Show agent details when hovering over a function/class
- **Document events**: Forward open/save/change to Remora as ContentChangedEvent
- **Commands**: Chat with agent, trigger agent, approve/reject proposals

### Implementation sketch

```python
"""Optional LSP adapter for Neovim integration."""
from __future__ import annotations

from lsprotocol import types as lsp
from pygls.server import LanguageServer


def create_lsp_server(node_store, event_store, runner) -> LanguageServer:
    server = LanguageServer("remora", "v2.0")

    @server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
    async def code_lens(params: lsp.CodeLensParams):
        file_path = params.text_document.uri.removeprefix("file://")
        nodes = await node_store.list_nodes(file_path=file_path)
        return [_node_to_lens(n) for n in nodes]

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    async def hover(params: lsp.HoverParams):
        file_path = params.text_document.uri.removeprefix("file://")
        line = params.position.line + 1
        nodes = await node_store.list_nodes(file_path=file_path)
        node = _find_node_at_line(nodes, line)
        if node:
            return _node_to_hover(node)
        return None

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(params: lsp.DidSaveTextDocumentParams):
        file_path = params.text_document.uri.removeprefix("file://")
        from remora.core.events import ContentChangedEvent
        await event_store.append(
            ContentChangedEvent(path=file_path, change_type="modified")
        )

    return server
```

### Why it's thin

The LSP server does NOT contain any agent logic. It just:
1. Reads from NodeStore to render UI elements (code lens, hover)
2. Writes to EventStore when editor events happen (save, change)
3. The runner picks up the events via subscriptions and handles everything

---

## 26. CLI Entry Point

### What it does

The CLI is the primary way to start Remora. One command starts everything:
discovery, the runner, and the web server.

### Implementation

```python
"""Remora CLI entry point."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click

from remora.core.config import load_config


@click.group()
def main():
    """Remora — Event-driven graph agent runner."""
    pass


@main.command()
@click.option("--project-root", type=click.Path(exists=True), default=".")
@click.option("--config", "config_path", type=click.Path())
@click.option("--port", default=8080, help="Web UI port")
@click.option("--no-web", is_flag=True, help="Disable web UI")
def start(project_root: str, config_path: str | None, port: int, no_web: bool):
    """Start Remora: discover code, run agents, serve web UI."""
    asyncio.run(_start(Path(project_root), config_path, port, no_web))


async def _start(project_root: Path, config_path: str | None, port: int, no_web: bool):
    import sqlite3
    from remora.core.config import load_config
    from remora.core.events import EventStore, EventBus, SubscriptionRegistry
    from remora.core.graph import NodeStore
    from remora.core.workspace import CairnWorkspaceService
    from remora.core.runner import AgentRunner
    from remora.code.reconciler import reconcile_on_startup

    config = load_config(config_path)
    project_root = project_root.resolve()

    # Initialize shared SQLite connection
    db_path = project_root / config.swarm_root / "remora.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    lock = asyncio.Lock()

    # Initialize components
    event_bus = EventBus()
    node_store = NodeStore(conn, lock)
    await node_store.create_tables()

    subscriptions = SubscriptionRegistry(conn, lock)
    event_store = EventStore(db_path, subscriptions=subscriptions, event_bus=event_bus)
    await event_store.initialize()

    workspace_service = CairnWorkspaceService(config, project_root)
    await workspace_service.initialize()

    # Run initial discovery
    logging.info("Starting code discovery...")
    await reconcile_on_startup(config, node_store, event_store, workspace_service, project_root)

    # Create runner
    runner = AgentRunner(event_store, node_store, workspace_service, config)

    # Start runner + web server concurrently
    tasks = [asyncio.create_task(runner.run_forever())]

    if not no_web:
        from remora.web.server import create_app
        import uvicorn
        app = create_app(event_store, node_store, event_bus, runner)
        web_config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
        server = uvicorn.Server(web_config)
        tasks.append(asyncio.create_task(server.serve()))
        logging.info(f"Web UI: http://127.0.0.1:{port}")

    logging.info("Remora started. Ctrl+C to stop.")
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        runner.stop()
        await workspace_service.close()
```

### Usage

```bash
# Start with defaults (discovers from src/, serves web on :8080)
remora start

# Custom project root and port
remora start --project-root /path/to/project --port 9090

# Headless mode (no web UI)
remora start --no-web
```

---

## Part VI: Testing & Operations

---

## 27. Testing Strategy

### Unit tests

Each core module has its own test file. Use `pytest-asyncio` for async tests
and `tmp_path` for isolated SQLite databases.

**What to test per module:**

| Module | Key tests |
|--------|-----------|
| `config.py` | Default values, YAML loading, env var expansion |
| `node.py` | CodeNode creation, `to_row()` / `from_row()` roundtrip, JSON list serialization |
| `events.py` | EventBus emit/subscribe, EventStore append/query, SubscriptionRegistry pattern matching |
| `graph.py` | NodeStore CRUD, edge operations, filtering |
| `workspace.py` | AgentWorkspace read/write/list, CairnWorkspaceService provisioning |
| `grail.py` | Tool discovery from workspace, GrailTool execution with mock externals |
| `runner.py` | Cooldown logic, depth limit, trigger → turn execution (with mock kernel) |
| `discovery.py` | Python function discovery, class discovery, nested methods |
| `projections.py` | CSTNode → CodeNode conversion, hash change detection, provisioning trigger |
| `reconciler.py` | Full pipeline: source files → nodes in graph |

### Integration tests

```python
@pytest.mark.asyncio
async def test_full_turn_execution(tmp_path):
    """Trigger an agent and verify it executes a tool."""
    # 1. Set up all components (config, stores, workspace)
    # 2. Create a CodeNode and provision its workspace
    # 3. Write a simple .pym tool to the workspace
    # 4. Trigger the agent
    # 5. Verify the tool was called (check events)
```

### Contract tests

Test the externals contract — verify every external function works:

```python
@pytest.mark.asyncio
async def test_externals_contract(tmp_path):
    """Verify every external in the contract is callable and returns expected types."""
    externals = build_externals(...)

    # Workspace ops
    assert await externals["write_file"]("test.txt", "hello") == True
    assert await externals["read_file"]("test.txt") == "hello"
    assert await externals["file_exists"]("test.txt") == True
    assert "test.txt" in await externals["list_dir"](".")

    # Graph ops
    assert isinstance(await externals["graph_query_nodes"](None, None), list)

    # Event ops
    assert await externals["event_emit"]("TestEvent", {}) == True

    # Communication
    assert await externals["send_message"]("target_id", "hello") == True

    # Identity
    assert isinstance(externals["my_node_id"], str)
```

---

## 28. Data Flow Walkthrough

Let's trace a complete flow: **a human sends a chat message to an agent, and
the agent rewrites its own code.**

### Step 1: Human sends message via web UI

```
Browser: POST /api/chat {"node_id": "src/auth.py::validate", "message": "Add input validation"}
    │
    ▼
web/server.py: creates HumanChatEvent(to_agent="src/auth.py::validate", message="Add input validation")
    │
    ▼
EventStore.append(event)
    ├─► EventBus.emit(event)              → SSE → browser shows "message sent"
    └─► SubscriptionRegistry.get_matching_agents(event)
            └─► agent "src/auth.py::validate" has subscription: to_agent="src/auth.py::validate"
                    └─► trigger_queue.put(("src/auth.py::validate", event))
```

### Step 2: Runner picks up the trigger

```
AgentRunner.run_forever() → consumes from trigger_queue
    │
    ├─► Cooldown check: has this agent been triggered in the last 1000ms? No → proceed
    ├─► Depth check: is cascade depth < 5? Yes → proceed
    │
    ▼
AgentRunner._execute_turn(trigger)
    │
    ├─► NodeStore.get_node("src/auth.py::validate") → CodeNode
    ├─► NodeStore.set_status("src/auth.py::validate", "running")
    │       └─► EventBus → SSE → browser shows node turning orange
    │
    ├─► workspace_service.get_agent_workspace("src/auth.py::validate") → AgentWorkspace
    │
    ├─► workspace.read("_bundle/bundle.yaml") → system_prompt, model, max_turns
    │
    ├─► discover_tools(workspace, externals) → [rewrite_self, send_message, subscribe, ...]
    │
    ├─► _build_externals() → dict of 16+ async functions
    │
    ├─► create_kernel(model, tools) → AgentKernel
    │
    ▼
kernel.run([system_prompt, user_prompt], tool_schemas, max_turns=8)
```

### Step 3: LLM decides to use rewrite_self

```
LLM receives:
    System: "You are an autonomous code agent..."
    User: "# Node: validate\nType: function | File: src/auth.py:10-25\n## Source Code\n..."

LLM responds with tool call:
    {tool: "rewrite_self", arguments: {new_source: "def validate(token: str) -> bool:\n    if not token:\n        raise ValueError('Token required')\n    ..."}}

    │
    ▼
GrailTool.execute(arguments) → runs rewrite_self.pym
    │
    ├─► calls @external propose_rewrite(new_source)
    │       │
    │       └─► creates RewriteProposalEvent
    │           ├─► EventStore.append()
    │           │       └─► EventBus → SSE → browser shows proposal in sidebar
    │           └─► NodeStore.set_status("pending_approval")
    │
    └─► returns "Rewrite proposal created: abc123"
```

### Step 4: Human approves

```
Browser: POST /api/approve {"proposal_id": "abc123"}
    │
    ▼
web/server.py: reads proposal from EventStore, applies the diff to the file on disk
    │
    ├─► writes new source to src/auth.py
    ├─► emits ContentChangedEvent(path="src/auth.py")
    │       └─► SubscriptionRegistry matches → all agents watching this file get triggered
    └─► NodeStore.set_status("idle")
```

### The full loop takes ~5 seconds

Most of that time is the LLM inference. The Python plumbing (event routing,
workspace access, tool execution) is milliseconds.

---

## 29. Glossary

| Term | Definition |
|------|-----------|
| **Agent** | A CodeNode that can be triggered, run an LLM turn, and take actions via tools |
| **AgentRunner** | The single execution coordinator. Consumes triggers, runs turns. |
| **AgentWorkspace** | A Cairn sandbox filesystem for one agent. Contains `_bundle/`, `notes/`, `chat/`, etc. |
| **Bundle** | A `bundle.yaml` + `tools/*.pym` directory that configures an agent's behavior |
| **Bundle-in-workspace** | The pattern where each agent's bundle lives inside its own workspace, not on disk |
| **Cairn** | Library providing sandboxed, SQLite-backed virtual filesystems |
| **CodeNode** | Pydantic model representing a code element that is also an agent |
| **Correlation ID** | A UUID that groups related events across a chain of agent interactions |
| **CSTNode** | Immutable data object from tree-sitter discovery. Becomes a CodeNode. |
| **EventBus** | In-memory pub/sub for real-time event distribution (SSE, UI) |
| **EventStore** | Append-only SQLite event log with subscription-based trigger routing |
| **Externals** | The dict of ~16 async functions passed to `.pym` scripts at execution time |
| **Grail** | Sandboxed scripting language for agent tools (`.pym` files) |
| **GrailTool** | A wrapper that loads a `.pym` script and presents it as a tool to the LLM |
| **Kernel** | `structured_agents.AgentKernel` — the LLM message/tool loop |
| **NodeStore** | SQLite-backed graph of CodeNode objects and edges |
| **Projection** | The process of converting CSTNodes to CodeNodes and storing them in the graph |
| **Reconciler** | Watches source files, runs discovery, updates the graph |
| **SSE** | Server-Sent Events — HTTP streaming from server to browser |
| **Subscription** | A persistent pattern (event types, agent filter, path glob) that routes events to an agent |
| **SubscriptionRegistry** | SQLite-backed registry of all subscriptions, with in-memory cache |
| **Template bundle** | A bundle directory under `bundles/` that gets copied into agent workspaces |
| **Trigger** | A queued request to run an agent turn, produced when an event matches a subscription |
| **Turn** | One complete cycle: load agent → build context → run LLM → execute tools → emit events |
| **.pym** | File extension for Grail scripts. Pronounced "pim" |
