# Expanded Web UI — Brainstorming

> How might remora-v2 expose a web interface that lets users fully generate, view, interact with, and modify codebases without ever opening a code editor?

---

## Table of Contents

1. **Current State** — What the existing web UI provides today and where it stops short.
2. **Vision & Principles** — The north-star experience; what "code-free codebase interaction" means.
3. **User Journeys** — Concrete scenarios for the two primary modes: exploring an existing codebase and creating a new one from scratch.
4. **Information Architecture** — The surfaces, panels, and navigation model the UI needs.
5. **Core Capabilities** — The feature set required, organized by interaction type (view, navigate, edit, generate, review).
6. **Agent Interaction Model** — How the user talks to agents, how agents present their work, and how approvals flow.
7. **Backend API Additions** — New endpoints, SSE events, and data models needed beyond the current server.py.
8. **Frontend Architecture** — Technology choices, component structure, and state management for a richer SPA.
9. **Codebase Generation Flow** — End-to-end design for "create a new project from a description."
10. **Implementation Roadmap** — Phased plan from today's UI to the full vision.
11. **Alternative Approaches** — Other paradigms we considered and why the primary design was chosen.

---

## 1. Current State

### What Exists

The v2 web UI (`web/server.py` + `web/static/index.html`) is a **monitoring and light-interaction dashboard**:

| Capability | Details |
|---|---|
| **Graph visualization** | Sigma.js force-directed graph showing nodes (functions, classes, methods) colored by type/status. File-clustered layout with ForceAtlas2. |
| **Node inspection** | Click a node → sidebar shows name, type, status, file path, line range, source code snippet. |
| **Agent panel** | Per-node event stream (start, complete, error, messages, tool results). Chat input to send `AgentMessageEvent` to a selected node. |
| **Proposal review** | View diff, accept, or reject `RewriteProposalEvent`s. Materializes workspace files to disk on accept. |
| **Human input** | Respond to `HumanInputRequestEvent`s inline. |
| **SSE streaming** | Real-time event feed with replay. Timeline view of all events. |
| **Cursor following** | LSP cursor focus → companion panel shows the focused node's source. |
| **Health/metrics** | `/api/health` endpoint with node count and metrics snapshot. |

### What's Missing

The current UI is a **window into** the system, not a **workspace for** the user. It cannot:

- **Navigate a file tree** — no directory/file browser, no way to see overall project structure.
- **Read arbitrary files** — only sees source code of discovered nodes, not the full file or non-code files (configs, READMEs, assets).
- **Edit code** — no inline editor. The only write path is accepting an agent's rewrite proposal.
- **Create anything** — no ability to create files, directories, or projects.
- **Search** — no full-text or semantic search across the codebase.
- **Orchestrate agents** — can chat with individual nodes, but can't assign high-level tasks, trigger multi-agent workflows, or express intent like "refactor this module."
- **Provide project context** — can't show dependency graphs, test results, git history, or documentation.

The gap between "monitoring dashboard" and "web-native development environment" is large but tractable, because remora-v2's backend already has most of the primitives (events, actors, workspaces, tools, file reconciliation).

---

## 2. Vision & Principles

### The North Star

A user opens the remora web UI, describes what they want ("build me a FastAPI microservice that manages a to-do list with SQLite"), and watches the system generate it — scaffold the project structure, create files, write code, run tests. They explore the result through a structured view (not raw source), ask agents to make changes ("add pagination to the list endpoint"), review diffs, approve them, and iterate. They never need to open VS Code.

For existing codebases, the user points remora at a repo, the graph populates, and they can browse, understand, and modify the codebase through the web UI — navigating by structure (file tree, call graph, dependency map) rather than by memory of file paths.

### Design Principles

1. **Structure over text.** Show the codebase as a navigable structure (trees, graphs, outlines) with source code available on demand — not as a wall of text the user must parse.

2. **Intent over keystrokes.** The primary interaction is expressing intent to agents ("make this function async," "add error handling here," "create a REST endpoint for users") rather than typing code character by character.

3. **Progressive disclosure.** The surface defaults to high-level views (project tree, module summaries, agent status). The user drills down to source code only when they choose to.

4. **Agent-mediated editing.** All code changes flow through agents → proposals → review → accept/reject. The user is an approver and director, not a typist. Direct editing is possible but secondary.

5. **Real-time feedback.** Every agent action, file change, and system event is visible as it happens via SSE. The UI is alive, not a static page you refresh.

6. **Single-page, no build step.** Stay with the current approach of a single HTML file with inline JS/CSS for as long as possible. Only move to a build tool (Vite, etc.) when complexity genuinely demands it.

7. **Backend-first features.** Every UI capability maps to a clean REST/SSE API. The frontend is a consumer of well-designed endpoints, not a monolith with embedded logic.

---

## 3. User Journeys

### Journey A: Exploring an Existing Codebase

**Scenario:** A developer inherits a Python project with 50 files. They want to understand its structure and make a targeted change.

1. **Open** — User navigates to `localhost:8765`. The file tree panel shows the project root with directories and files. The graph shows discovered nodes.

2. **Browse** — User clicks through the file tree: `src/` → `models/` → `user.py`. The main panel shows an outline of `user.py`: the `User` class, its methods, its imports. Clicking a method shows its source code.

3. **Understand** — User selects the `User` class node and sees:
   - Source code (read-only, syntax-highlighted)
   - Agent summary (if companion digests exist): "SQLAlchemy model representing a user. Has password hashing, email validation, and relationship to Order."
   - References: which other nodes call/import this class
   - Recent changes: last content-changed events for this file

4. **Ask** — User types in the command bar: "Add a `last_login` timestamp field to the User model and update the migration." The system routes this as an `AgentMessageEvent` to the `User` class agent.

5. **Watch** — The agent panel shows the agent thinking, calling tools, reading the migration files. The graph pulses the relevant nodes.

6. **Review** — A `RewriteProposalEvent` appears. The UI shows a split diff: old vs. new for `user.py` and `migrations/versions/xxx.py`. User clicks "Accept."

7. **Verify** — The file tree updates to reflect the changes. The user clicks "Run tests" (a global action that broadcasts to the test-agent). Test results stream in.

### Journey B: Creating a New Codebase from Scratch

**Scenario:** A user wants to create a new FastAPI microservice.

1. **New Project** — User clicks "New Project" in the top bar. A dialog asks for: project name, base directory, and a description. User types: "A FastAPI microservice for managing a book inventory with CRUD endpoints, SQLite storage, and Pydantic models."

2. **Plan** — The system creates a "project architect" agent (a virtual agent or a special root node). It generates a project plan: proposed directory structure, file list, key design decisions. This is presented as a structured outline in the main panel, not as a wall of text.

3. **Approve structure** — User reviews the plan. They can chat with the architect: "Use poetry instead of pip, and add a Dockerfile." The plan updates. User clicks "Generate."

4. **Generate** — The architect delegates to per-file agents. The file tree populates in real time as files are scaffolded. The graph grows. Progress shows as a checklist: `pyproject.toml` ✓, `src/app/main.py` ✓, `src/app/models.py` ⏳...

5. **Iterate** — Once generation is complete, the user browses the result using the same Journey A interface. They can ask for changes, run tests, and refine.

### Journey C: High-Level Refactoring

**Scenario:** User wants to refactor a module from synchronous to async.

1. **Select scope** — User multi-selects several files or a directory in the file tree. Clicks "Refactor..." in the action bar.

2. **Describe intent** — Dialog: "Convert all database calls in these files from synchronous to async using `asyncio` and `aiosqlite`."

3. **Coordinate** — The system creates a coordinating agent that fans out to the per-node agents for each affected function/class. The timeline shows parallel agent work.

4. **Batch review** — All proposals appear in a "Review Queue" panel. User can review each diff, accept all, reject specific ones, or provide feedback.

---

## 4. Information Architecture

### Layout Model

```
┌──────────────────────────────────────────────────────────────────────┐
│  Top Bar: project name | command bar | actions (New, Run, Settings)  │
├──────────┬───────────────────────────────────────┬───────────────────┤
│          │                                       │                   │
│  Left    │        Main Panel                     │   Right           │
│  Panel   │                                       │   Panel           │
│          │  (graph / file view / outline /        │                   │
│  File    │   diff / project plan)                │  Agent Panel      │
│  Tree    │                                       │  + Chat           │
│  +       │                                       │  + Proposals      │
│  Outline │                                       │  + Timeline       │
│          │                                       │                   │
├──────────┴───────────────────────────────────────┴───────────────────┤
│  Bottom Bar: status | active agents count | SSE connection | errors  │
└──────────────────────────────────────────────────────────────────────┘
```

### Panel Descriptions

| Panel | Content | Resizable |
|---|---|---|
| **Left Panel** | File tree (directory browser) at top. Outline (symbols in current file) below. Collapsible. | Yes, drag border |
| **Main Panel** | The primary content area. Switches between: graph view, file viewer (syntax-highlighted read-only), diff viewer, project plan, review queue. Tab bar at top for multiple open views. | Fills remaining space |
| **Right Panel** | Agent interaction. Shows the selected agent's event stream, chat input, pending proposals, companion digest. Collapsible. | Yes, drag border |
| **Top Bar** | Project name/breadcrumb. Global command bar (natural language input). Action buttons. | No |
| **Bottom Bar** | SSE connection status. Count of running agents. Error indicators. | No |

### Navigation Model

- **File tree** → click file → main panel shows file view (outline + source)
- **Graph** → click node → main panel shows node detail, right panel shows agent
- **Command bar** → type intent → routes to appropriate agent(s), right panel shows progress
- **Breadcrumb** → shows current location (project > file > symbol), clickable for navigation
- **Tabs** → main panel supports multiple open views (like browser tabs, not editor tabs)

---

## 5. Core Capabilities

### 5.1 View & Navigate

| Feature | Description |
|---|---|
| **File tree** | Read project directory recursively. Show files/dirs with icons by type. Lazy-load deep trees. Highlight files with active agents. |
| **File viewer** | Syntax-highlighted source code, read-only by default. Line numbers. Click a symbol → jump to its node. |
| **Symbol outline** | List of functions, classes, methods in the current file. Click to scroll. Shows agent status per symbol. |
| **Graph view** | The existing Sigma graph, enhanced with better layout, zoom controls, filtering by file/type/status. |
| **Search** | Global search bar. Full-text search across all files. Semantic search if embeddy is available. Results as a file list with match previews. |
| **Dependency view** | For a selected node, show what it imports/calls and what imports/calls it. Visual or list format. |
| **Git integration** | Show current branch, recent commits, uncommitted changes. Diff view for any commit. |

### 5.2 Edit & Generate

| Feature | Description |
|---|---|
| **Natural language commands** | Type intent in command bar → system routes to agent(s) → proposals generated. |
| **Scoped commands** | Right-click a file/node → "Ask agent to..." → context-aware intent. |
| **Inline edit** | Optional: click "Edit" on a file view → switch to a lightweight code editor (CodeMirror/Monaco). Save triggers `ContentChangedEvent`. |
| **Proposal review** | Split diff view for rewrite proposals. Accept, reject, or provide feedback. Batch review for multi-file changes. |
| **New file/directory** | Create files and directories from the file tree. Templates for common patterns. |
| **Project scaffolding** | "New Project" wizard: name, description, tech stack → agent generates full project structure. |

### 5.3 Observe & Control

| Feature | Description |
|---|---|
| **Agent dashboard** | List all active agents with status. Click to focus. Kill/restart controls. |
| **Event timeline** | Chronological feed of all system events, filterable by type, agent, file. |
| **Review queue** | All pending proposals in one place. Bulk accept/reject. |
| **Test runner** | Trigger test runs. Show pass/fail results per test, with output on failure. |
| **Metrics** | LLM token usage, agent turn counts, error rates. |

---

## 6. Agent Interaction Model

### Current Model (v2 today)

The user interacts with agents one at a time: select a node in the graph → chat in the sidebar → wait for response/proposal. This is like having a phone with no conference calling — you can talk to one agent at a time.

### Expanded Model

#### 6.1 Command Bar as Primary Input

The **command bar** at the top of the UI is the primary interaction point. It accepts natural language and routes intelligently:

- **Node-scoped**: "Make `User.validate_email` use regex instead of string matching" → routes to the `User.validate_email` agent.
- **File-scoped**: "Add type hints to all functions in utils.py" → routes to all agents in `utils.py`.
- **Project-scoped**: "Add a Dockerfile and docker-compose.yml" → routes to a virtual architect agent or creates new file agents.
- **Query**: "How does authentication work in this codebase?" → triggers a search/summary flow, returns an answer in the main panel (not a code change).

#### 6.2 Multi-Agent Coordination

When a command affects multiple agents, the UI shows a **task tracker**:

```
┌─────────────────────────────────────────┐
│  Task: Add type hints to utils.py       │
│  ┌─────────────────────────────────┐    │
│  │ ✓ parse_config — complete       │    │
│  │ ⏳ load_template — in progress   │    │
│  │ ○ render_output — pending       │    │
│  └─────────────────────────────────┘    │
│  [Review All] [Cancel]                  │
└─────────────────────────────────────────┘
```

Each sub-task links to its agent's proposal. "Review All" opens a batch diff view.

#### 6.3 Approval Flow

Three modes, configurable per session:

1. **Manual** (default): Every proposal requires explicit accept/reject. Best for learning a new codebase.
2. **Auto-minor**: Proposals tagged as "cosmetic" or "formatting" auto-accept. Structural changes require review.
3. **Auto-all**: Everything auto-accepts. Useful during initial scaffolding of a new project.

#### 6.4 Feedback Loop

When the user rejects a proposal, they provide feedback. The agent receives a `RewriteRejectedEvent` with the feedback and can make another attempt. The UI shows the iteration history: attempt 1 → rejected ("don't use global state") → attempt 2 → accepted.

---

## 7. Backend API Additions

### New Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/files` | GET | List project files/directories. Query params: `path` (directory), `recursive`, `depth`. Returns tree structure. |
| `/api/files/{path}` | GET | Read file contents. Returns source with syntax info. |
| `/api/files/{path}` | PUT | Write/update file contents. Emits `ContentChangedEvent`. |
| `/api/files/{path}` | DELETE | Delete a file. Emits appropriate event. |
| `/api/files/{path}/mkdir` | POST | Create directory. |
| `/api/search` | GET | Full-text search. Query params: `q`, `file_glob`, `limit`. Returns matches with context. |
| `/api/search/semantic` | GET | Semantic search via embeddy (if available). Query: `q`, `collection`, `limit`. |
| `/api/command` | POST | Submit a natural-language command. Body: `{ "text": "...", "scope": "node|file|project", "target": "..." }`. Returns a task ID. |
| `/api/tasks` | GET | List active command-tasks with status. |
| `/api/tasks/{id}` | GET | Get task detail (sub-tasks, proposals, status). |
| `/api/proposals` | GET | *(existing, enhanced)* List all pending proposals. Add filtering by file, agent, time. |
| `/api/proposals/batch` | POST | Accept or reject multiple proposals at once. |
| `/api/git/status` | GET | Git working tree status. |
| `/api/git/log` | GET | Recent commits. Query: `limit`, `path`. |
| `/api/git/diff` | GET | Diff for a commit or working tree. |
| `/api/agents` | GET | List all agents with status, node info, last activity. |
| `/api/agents/{id}/kill` | POST | Stop a running agent. |
| `/api/project/new` | POST | Start a new project generation. Body: `{ "name": "...", "path": "...", "description": "..." }`. |

### New SSE Event Types

| Event | Purpose |
|---|---|
| `TaskCreatedEvent` | A multi-agent command-task was created. |
| `TaskProgressEvent` | A sub-task within a command-task changed status. |
| `TaskCompleteEvent` | All sub-tasks in a command-task are done. |
| `FileCreatedEvent` | A new file was created (distinct from `ContentChangedEvent`). |
| `FileDeletedEvent` | A file was deleted. |
| `TestResultEvent` | A test run completed with results. |

### Data Models

```python
@dataclass
class CommandTask:
    task_id: str
    text: str               # original natural-language command
    scope: str              # "node", "file", "project"
    target: str | None      # node_id, file_path, or None for project-wide
    status: str             # "planning", "executing", "reviewing", "complete", "failed"
    sub_tasks: list[SubTask]
    created_at: float

@dataclass
class SubTask:
    agent_id: str
    status: str             # "pending", "running", "proposed", "accepted", "rejected"
    proposal_id: str | None
```

---

## 8. Frontend Architecture

### Staying Single-File as Long as Possible

The current single-file approach (`index.html` with inline JS/CSS) is excellent for simplicity and zero-build deployment. The expanded UI pushes against this, but we can stretch it further using a few patterns:

#### Component-via-Functions Pattern

Instead of a framework, organize the JS as a set of render functions that manage DOM sections:

```javascript
// Each "component" is a render function that owns a DOM container
const FileTree = {
  el: document.getElementById("file-tree"),
  state: { tree: null, expanded: new Set() },
  async load(path = "/") { /* fetch /api/files?path=... */ },
  render() { /* build DOM from state */ },
};

const FileViewer = {
  el: document.getElementById("file-viewer"),
  state: { path: null, content: null },
  async open(path) { /* fetch /api/files/path */ },
  render() { /* syntax-highlighted source */ },
};
```

This keeps the architecture simple while providing structure. Each "component" owns its state and DOM subtree.

#### When to Upgrade

Move to a build tool + framework when ANY of:
- The single HTML file exceeds ~3,000 lines
- We need code splitting (lazy-load heavy components like a code editor)
- We need TypeScript for type safety across many interacting components
- Three or more developers are working on the frontend simultaneously

If/when we upgrade, the natural choice is:
- **Vite** for build tooling (fast, simple)
- **Preact or Svelte** for reactivity (lightweight, no virtual DOM overhead)
- **CodeMirror 6** for inline editing (modular, lightweight)

### Syntax Highlighting

For read-only source viewing without a build step:
- **Prism.js** or **highlight.js** loaded from CDN — handles Python, JS, YAML, etc.
- Applied to `<pre><code>` blocks on render
- Minimal footprint, no editor overhead

For inline editing (Phase 3+):
- **CodeMirror 6** loaded from CDN — tree-shakeable, but CDN bundles are ~150KB
- Provides full editor: syntax highlighting, bracket matching, basic autocomplete

### State Management

A simple pub/sub event emitter shared across components:

```javascript
const AppState = {
  _listeners: new Map(),
  selectedNode: null,
  selectedFile: null,
  openTabs: [],

  set(key, value) {
    this[key] = value;
    (this._listeners.get(key) || []).forEach(fn => fn(value));
  },
  on(key, fn) {
    if (!this._listeners.has(key)) this._listeners.set(key, []);
    this._listeners.get(key).push(fn);
  }
};
```

Components subscribe to state changes they care about. SSE events update `AppState`, which triggers re-renders of affected components.

---

## 9. Codebase Generation Flow

This is the most novel capability — creating a project from a natural-language description without touching a code editor.

### Step-by-Step Flow

#### 1. User Input

The "New Project" dialog collects:
- **Name**: `book-inventory-api`
- **Base path**: `/home/user/projects/` (defaults to a configured workspace root)
- **Description**: Free-form text describing the desired project

Optional structured hints:
- **Language/framework**: Python + FastAPI (auto-detected from description if not specified)
- **Dependencies**: Specific libraries to use
- **Conventions**: "Use Google-style docstrings," "Prefer dataclasses over Pydantic"

#### 2. Planning Phase

The system creates a **project architect agent** (a virtual agent with the `system` bundle + a `scaffold.pym` tool). The architect:

1. Analyzes the description
2. Proposes a directory structure + file manifest
3. Identifies key design decisions (ORM choice, testing framework, etc.)

The UI shows this as a structured plan:

```
book-inventory-api/
├── pyproject.toml
├── README.md
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py          ← FastAPI app entry point
│       ├── models.py         ← SQLAlchemy models
│       ├── schemas.py        ← Pydantic request/response schemas
│       ├── database.py       ← DB connection + session management
│       └── routers/
│           └── books.py      ← CRUD endpoints
└── tests/
    ├── conftest.py
    └── test_books.py
```

Each file has a one-line description. The user can:
- Add/remove files
- Change descriptions
- Chat with the architect ("Also add an `authors` table with a many-to-many relationship to books")

#### 3. Generation Phase

On "Generate," the architect creates the project directory, then **delegates file generation to per-node agents**:

1. For each file in the manifest, the architect emits an event (or creates a virtual node) that triggers the relevant agent
2. Agents generate file contents using their context (the plan, other files already generated, conventions)
3. Files are written to workspace first, then materialized to disk via the normal proposal flow (or auto-accepted if the user chose auto-all mode)

The UI shows progress as a checklist with real-time updates:

```
Generating book-inventory-api...
✓ pyproject.toml
✓ src/app/__init__.py
✓ src/app/main.py
⏳ src/app/models.py (agent working...)
○ src/app/schemas.py
○ src/app/database.py
○ src/app/routers/books.py
○ tests/conftest.py
○ tests/test_books.py
```

#### 4. Validation Phase

After generation completes:
1. The system runs a syntax check (import the modules, check for parse errors)
2. If a test runner is configured, runs the test suite
3. Results appear in the UI: green/red indicators per file, test output

#### 5. Iteration

The user now has a fully generated project visible in the file tree. They use the normal explore/modify flow (Journey A) to refine it.

### Key Design Decisions

- **Architect agent as coordinator**: Uses the existing virtual agent mechanism. Gets a system prompt specialized for project planning. Has tools for directory creation and file delegation.
- **Per-file parallelism**: Independent files (e.g., `models.py` and `conftest.py`) can generate in parallel. Dependent files (e.g., `schemas.py` depends on `models.py`) generate sequentially.
- **Dependency ordering**: The architect produces a dependency-ordered generation plan. The UI reflects this ordering in the progress display.
- **Template system**: For very common patterns (FastAPI app, CLI tool, library package), pre-built templates can skip the planning phase. Templates are Grail scripts that scaffold structure directly.

---

## 10. Implementation Roadmap

### Phase 1: File Explorer (the foundation)

**Goal:** Replace the monitoring-only UI with a usable codebase browser.

| Task | New/Modified | Est. Lines |
|---|---|---|
| `/api/files` endpoint (list + read) | `web/server.py` | +60 |
| File tree component in frontend | `index.html` | +150 |
| File viewer with syntax highlighting (Prism.js) | `index.html` | +100 |
| Symbol outline (from existing node data) | `index.html` | +80 |
| Three-panel layout (left/main/right) | `index.html` CSS | +120 |
| Tab system for main panel | `index.html` | +80 |
| **Total** | | **~590** |

**Outcome:** User can browse files, read source code, and see the node graph — all in one UI.

### Phase 2: Command & Control

**Goal:** User can issue natural-language commands and review proposals in a structured way.

| Task | New/Modified | Est. Lines |
|---|---|---|
| Command bar component | `index.html` | +100 |
| `/api/command` endpoint + routing logic | `web/server.py` + new `web/commands.py` | +150 |
| `CommandTask` data model + storage | `core/events/types.py` | +40 |
| Task tracker component | `index.html` | +120 |
| Enhanced proposal review (batch, feedback) | `index.html` + `web/server.py` | +150 |
| Approval mode selector (manual/auto-minor/auto-all) | `index.html` + `web/server.py` | +60 |
| **Total** | | **~620** |

**Outcome:** User can direct agents from the web UI and review/approve changes efficiently.

### Phase 3: Project Generation

**Goal:** User can create new projects from descriptions.

| Task | New/Modified | Est. Lines |
|---|---|---|
| "New Project" dialog component | `index.html` | +120 |
| `/api/project/new` endpoint | `web/server.py` | +80 |
| Architect virtual agent config + prompt | `bundles/architect-agent/` | +60 |
| Generation progress tracker | `index.html` | +100 |
| `/api/files/{path}` PUT + DELETE + mkdir | `web/server.py` | +80 |
| Validation step (syntax check, test run) | `web/server.py` | +60 |
| **Total** | | **~500** |

**Outcome:** User can create a new project from a description and watch it generate in real time.

### Phase 4: Polish & Power Features

**Goal:** Quality-of-life features for power users.

| Task | New/Modified | Est. Lines |
|---|---|---|
| Git integration (status, log, diff) | `web/server.py` | +120 |
| Global search (full-text + semantic) | `web/server.py` + `index.html` | +150 |
| Inline code editor (CodeMirror) | `index.html` | +200 |
| Agent dashboard (list, status, kill) | `index.html` + `web/server.py` | +120 |
| Test runner integration | `web/server.py` + `index.html` | +100 |
| Keyboard shortcuts | `index.html` | +60 |
| **Total** | | **~750** |

### Total Estimated New Code

| Phase | Lines |
|---|---|
| Phase 1: File Explorer | ~590 |
| Phase 2: Command & Control | ~620 |
| Phase 3: Project Generation | ~500 |
| Phase 4: Polish | ~750 |
| **Grand Total** | **~2,460** |

This is substantial but not unreasonable. Each phase delivers standalone value. The backend changes are modest because v2's core already provides most of the needed primitives.

---

## 11. Alternative Approaches

### A. Embedded IDE (Monaco/VS Code in Browser)

Ship a full code editor (Monaco or VS Code for Web) as the main panel.

**Pros:**
- Familiar editing experience for developers
- Full syntax highlighting, intellisense, multi-cursor, etc.
- Many users already know the keybindings

**Cons:**
- Massive bundle size (~5MB+ for Monaco)
- Fights against the "intent over keystrokes" principle — gives users a code editor and they'll use it as one
- Remora's value is the agent layer, not the editor layer. We'd be building a worse VS Code.
- Requires a build step and significant frontend infrastructure

**Verdict:** Wrong direction. If users want to type code, they should use their real editor + remora's LSP integration. The web UI should offer what editors *can't*: agent-mediated interaction.

### B. Notebook Interface (Jupyter-style)

Present the codebase as a series of cells — some code, some markdown, some agent output. Users interact by adding cells.

**Pros:**
- Familiar to data scientists
- Natural mix of code and explanation
- Cell-level execution maps well to per-node agents

**Cons:**
- Codebases aren't linear — a notebook is a poor fit for a tree of files
- Loses the spatial understanding that the graph provides
- Doesn't handle multi-file projects naturally
- Requires reimagining remora's core abstractions

**Verdict:** Interesting for specific workflows (e.g., explaining a module step by step) but wrong as the primary paradigm.

### C. Chat-Only Interface (ChatGPT-style)

Just a big chat box. User describes what they want, agents respond with code in messages.

**Pros:**
- Simplest possible UI
- Very low implementation cost
- Users understand the pattern from ChatGPT, Copilot Chat, etc.

**Cons:**
- Loses spatial awareness of the codebase
- No way to browse, navigate, or understand existing code
- Code in chat messages is ephemeral — not connected to the file system
- The existing CLI already serves this role

**Verdict:** Too limited. The CLI already provides chat-style interaction. The web UI should add what the CLI can't: visual spatial awareness.

### D. Kanban/Card-Based Interface

Each file or component is a card on a board. Columns represent status (idle, in-progress, needs-review, complete). Users drag cards, open them for detail.

**Pros:**
- Visual, approachable, non-intimidating
- Good for project management overlay on top of code
- Maps well to agent status tracking

**Cons:**
- Doesn't work for codebases with hundreds of files
- Poor for understanding code structure and relationships
- Novelty over utility — developers don't think of code as cards

**Verdict:** Useful as a *view mode* for proposals/tasks (and the review queue somewhat resembles this), but not as the primary interface.

### E. Low-Code / Visual Programming (node-based editor)

Present the codebase as a visual flow: boxes for functions/classes, wires for calls/data flow. Users connect boxes to add logic.

**Pros:**
- Very "no code" — aligns with the vision of not looking at code
- Could be powerful for understanding data flow
- Some precedent (Node-RED, Unreal Blueprints)

**Cons:**
- Extremely complex to implement well
- Only works for certain program structures (data pipelines, event flows)
- General-purpose code (conditionals, error handling, string manipulation) is painful to express visually
- Remora's graph already provides the "visual structure" view; this would be a second, conflicting visual paradigm

**Verdict:** Interesting as a future visualization layer (e.g., showing the data flow for a specific request path) but not as the primary editing paradigm.

### F. Chosen Approach: Structured Browser + Agent-Mediated Editing

The design described in this document. Structure-first browsing (file tree, outline, graph) with natural-language commands routed to agents.

**Pros:**
- Builds on what already exists (graph, agent panel, proposals)
- Incrementally implementable (each phase adds value)
- Plays to remora's strength (the agent layer) rather than competing with editors
- Low frontend complexity (no build step needed for Phase 1-2)

**Cons:**
- Not a "wow" visual demo — it's a pragmatic design, not a flashy one
- The command routing system needs to be smart (NLP-level intent parsing) to feel magical
- Power users may want inline editing sooner than Phase 4

**Verdict:** This is the right default. It starts from remora's strengths, builds incrementally, and delivers the core value (agents doing the coding work while humans direct and review) without overbuilding.
