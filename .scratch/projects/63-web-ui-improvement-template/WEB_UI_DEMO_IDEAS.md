# Web UI & Demo Improvement Ideas

## Table of Contents

### Part I — Web UI Improvements

1. [Minimap / Overview Panel](#1-minimap--overview-panel) — A small inset map showing the full graph extent with a viewport rectangle
2. [Search & Focus Bar](#2-search--focus-bar) — Type-ahead search to find and zoom to any node by name, type, or file
3. [Node Status Animation](#3-node-status-animation) — Animated visual indicators when agents are running, waiting, or erroring
4. [Conversation History Drawer](#4-conversation-history-drawer) — Expandable panel showing full conversation history for the selected agent
5. [Graph Snapshot / Export](#5-graph-snapshot--export) — Button to export the current graph view as PNG or SVG
6. [Keyboard Navigation](#6-keyboard-navigation) — Arrow keys to move between nodes, Enter to select, Escape to deselect
7. [Edge Path Labels](#7-edge-path-labels) — Show edge type labels on hover or permanently along the edge path
8. [Notification Toasts for Key Events](#8-notification-toasts-for-key-events) — Transient toast messages for important events (errors, proposals, completions)
9. [Split-Pane Source Viewer](#9-split-pane-source-viewer) — Side-by-side view of a node's current source vs proposed rewrite
10. [Node Grouping / Collapse](#10-node-grouping--collapse) — Collapse a file column or directory box into a single aggregate node
11. [Semantic Search Integration](#11-semantic-search-integration) — Wire the existing /api/search into the UI with a search modal and result highlighting
12. [Dark/Light Theme Toggle](#12-darklight-theme-toggle) — CSS variable swap between dark and light palettes
13. [Responsive / Mobile Layout](#13-responsive--mobile-layout) — Stack sidebar below graph on narrow viewports
14. [Event Stream Filtering](#14-event-stream-filtering) — Filter the events panel by event type, agent, or severity
15. [Connection Quality Indicator](#15-connection-quality-indicator) — Show SSE latency, missed events, and reconnect history
16. [Breadcrumb Trail for Node Context](#16-breadcrumb-trail-for-node-context) — Show the containment path (dir > file > class > method) for the selected node

### Part II — Demo Showcase Ideas

17. [Guided Walkthrough Mode](#17-guided-walkthrough-mode) — A scripted step-by-step overlay that narrates what Remora is doing
18. [Live Coding Trigger](#18-live-coding-trigger) — Edit a file during the demo and watch agents react in real time
19. [Multi-Agent Collaboration Scenario](#19-multi-agent-collaboration-scenario) — Demo where multiple agents interact (review agent catches a bug, code agent fixes it)
20. [Human-in-the-Loop Showcase](#20-human-in-the-loop-showcase) — Demo that pauses for human input, showing the bidirectional chat
21. [Rewrite Proposal Workflow](#21-rewrite-proposal-workflow) — Demo ending with a proposal diff, accept/reject buttons, and code materialization
22. [Graph Evolution Replay](#22-graph-evolution-replay) — Replay the event history to show the graph building up over time
23. [Cursor-Following Demo (LSP)](#23-cursor-following-demo-lsp) — Show the companion panel tracking cursor movement in an editor
24. [Scale Stress Test](#24-scale-stress-test) — Demo with a larger codebase (50+ files) to show layout handles scale
25. [Before/After Comparison](#25-beforeafter-comparison) — Side-by-side screenshots showing graph before and after an agent makes changes
26. [Error Recovery Demo](#26-error-recovery-demo) — Deliberately trigger an agent error, show the error state, and demonstrate recovery

---

## Part I — Web UI Improvements

---

### 1. Minimap / Overview Panel

**Idea**: A small (150×100px) inset panel in the bottom-right corner of the graph canvas showing a zoomed-out silhouette of the entire graph. The current viewport is drawn as a translucent rectangle. Dragging the rectangle pans the main view.

**How it works**: Render a simplified version of all node positions as dots on a second tiny canvas. Listen to camera state changes and draw a viewport indicator. Mouse events on the minimap translate to camera pan commands.

**Pros**:
- Provides spatial awareness when zoomed in — users always know where they are in the graph
- Standard UX pattern familiar from IDEs, image editors, and map applications
- Helps when the graph is large enough that zoomed-in users lose context

**Cons**:
- Adds visual clutter for small graphs (< 20 nodes) where the full graph already fits on screen
- Requires maintaining a second rendering context synchronized with the main Sigma renderer
- The minimap dots need to be meaningful at tiny scale — colors must be saturated enough to read at 2px diameter

**Implications**:
- Needs camera state subscription (Sigma's `camera:updated` event)
- Must be drawn on a separate canvas overlaid on the graph container, not inside Sigma
- Should auto-hide when the entire graph fits within the viewport at current zoom

**Opportunities**:
- Could double as a quick-nav: clicking on a minimap region instantly pans there
- Could show active agents as pulsing dots for at-a-glance system status
- Natural evolution toward a "heatmap mode" where node activity frequency colors the minimap

---

### 2. Search & Focus Bar

**Idea**: A search input (triggered by `/` or `Ctrl+K`) that filters and highlights nodes by name, file path, node type, or status. Selecting a result zooms the camera to that node and opens it in the sidebar.

**How it works**: On keystroke, fuzzy-match against all graph node attributes (`label`, `file_path`, `node_type`, `status`). Render a dropdown of matches ranked by relevance. On selection, animate the camera to center on the node and call `selectNode()`.

**Pros**:
- Essential for graphs with 30+ nodes where visual scanning is slow
- Replaces the need to pan/zoom/scan when you know what you're looking for
- The `/api/nodes` endpoint already returns all data needed for client-side filtering

**Cons**:
- Requires a fuzzy matching algorithm (can be simple substring, but proper fuzzy matching is more polished)
- Dropdown UI needs careful z-index management to float above both the graph and filter bar
- On very large graphs, the full node list may be expensive to filter on every keystroke

**Implications**:
- Should debounce input (150ms) to avoid excessive re-filtering
- The dropdown should show node type icons/colors alongside names for quick identification
- Focus management: pressing `/` should not conflict with any Sigma keyboard shortcuts

**Opportunities**:
- Could integrate with the existing `/api/search` semantic search for natural-language queries ("find the function that handles discounts")
- Could support structured filters like `type:class status:running file:orders.py`
- History of recent searches/selections for quick re-navigation

---

### 3. Node Status Animation

**Idea**: Animated visual effects on nodes that are in non-idle states: a pulsing glow for `running`, a bouncing attention indicator for `awaiting_input`, a shaking/vibrating effect for `error`.

**How it works**: In the `drawNodeBoxLabel` function, use `Date.now()` to drive periodic visual changes — modulate border opacity, border width, or add a glow effect based on the current status. Request animation frames via Sigma's render loop.

**Pros**:
- Makes agent activity visible at a glance without reading the sidebar
- Draws the user's eye to nodes that need attention (`awaiting_input`, `error`)
- Creates a "living system" feel — the graph breathes and pulses as agents work

**Cons**:
- Continuous animation increases GPU/CPU usage (relevant for large graphs)
- Can be visually distracting if many agents are active simultaneously
- Animations in `drawNodeBoxLabel` require Sigma to refresh continuously, not just on data change

**Implications**:
- Need a `requestAnimationFrame` loop (or Sigma's `scheduleRefresh`) when any node has a non-idle status
- Should stop the animation loop when all nodes return to idle to save resources
- Animation speed/intensity should be configurable or at least tastefully subtle

**Opportunities**:
- The `running` animation could show progress-like effects (rotating border, expanding ring)
- `awaiting_input` could flash the accent color to demand attention
- Could add a small badge or counter showing the number of active/error nodes in the filter bar

---

### 4. Conversation History Drawer

**Idea**: Replace the current `#agent-stream` div with a full-featured conversation drawer that shows the complete message history for the selected agent, formatted as a chat thread with user/agent/system messages distinguished.

**How it works**: When a node is selected, fetch `/api/nodes/{node_id}/conversation` to get the full message history. Render each message as a chat bubble with role, timestamp, and content. Support scrolling through long conversations.

**Pros**:
- The current agent panel only shows cached SSE events — the conversation endpoint has the full LLM history
- Chat-bubble formatting is more readable than the current flat event list
- Users can see the full reasoning chain that led to a proposal or action

**Cons**:
- Conversations can be very long (dozens of messages) — needs virtualized scrolling or lazy loading
- Message content can include code blocks, tool results, and structured data that need formatting
- Fetching conversation on every node selection adds latency

**Implications**:
- The `/api/nodes/{node_id}/conversation` endpoint already exists with `history_limit` and `message_limit`
- Need a markdown-to-HTML renderer (or at minimum, code block detection and formatting)
- Should merge SSE live events with historical conversation data without duplication

**Opportunities**:
- Could add a "copy conversation" button for debugging or sharing
- Could highlight tool calls and tool results with special formatting
- Could show token usage per turn if that data becomes available

---

### 5. Graph Snapshot / Export

**Idea**: A camera icon button that captures the current graph view as a PNG image, including bounding boxes, labels, edges, and filter state.

**How it works**: Use Sigma's `getCanvases()` to get the underlying canvas elements. Composite them onto a single off-screen canvas in the correct layer order (boxes → edges → nodes → labels). Call `canvas.toBlob()` and trigger a download.

**Pros**:
- Essential for documentation, bug reports, and demos
- Captures the exact visual state the user sees
- No external dependencies — pure canvas API

**Cons**:
- Sigma uses multiple canvas layers — compositing order must match the visual stacking
- Bounding boxes are drawn on the edges canvas in `beforeRender`, which complicates the layer model
- High-DPI displays need `devicePixelRatio` handling to avoid blurry exports

**Implications**:
- The export should include the filter bar state and sidebar (or optionally exclude the sidebar)
- File name should include a timestamp: `remora-graph-20260327-221431.png`
- Could be tied to the zoom-reset button or have its own dedicated button

**Opportunities**:
- SVG export for vector-quality diagrams (would require re-rendering, not canvas capture)
- Could automatically capture and save snapshots at key moments (discovery complete, error state)
- Integration with the Playwright screenshot infrastructure already used for testing

---

### 6. Keyboard Navigation

**Idea**: Navigate the graph without a mouse — arrow keys move between nodes following the visual layout, Tab cycles through nodes, Enter selects, Escape deselects.

**How it works**: Maintain a "focused node" index. Arrow keys move to the nearest node in that direction (by graph coordinates). Enter triggers `selectNode()`. Escape clears selection and re-centers the camera. A visible focus ring distinguishes keyboard-focused from mouse-hovered nodes.

**Pros**:
- Accessibility improvement — the graph is currently mouse-only
- Power users prefer keyboard navigation for speed
- Natural fit for the deterministic grid layout (left/right moves between columns, up/down within columns)

**Cons**:
- "Nearest node in direction" logic is non-trivial for arbitrary layouts
- Conflicts with browser default arrow key scrolling — needs `preventDefault` management
- Focus ring rendering adds complexity to `drawNodeBoxLabel`

**Implications**:
- Must co-exist with mouse hover/click without confusion
- Tab order should follow the visual layout (left-to-right, top-to-bottom)
- Should work with screen readers via ARIA live regions for node announcements

**Opportunities**:
- Vim-style `h/j/k/l` as an alternative to arrow keys for developer audiences
- `g` + letter combinations for quick jumps (e.g., `gf` for functions, `gc` for classes)
- Command palette via `/` that merges search and keyboard commands

---

### 7. Edge Path Labels

**Idea**: Show the edge type (`imports`, `inherits`) as a small label along the edge path, either permanently or on hover.

**How it works**: In the `edgeReducer` or a custom edge renderer, place a text label at the midpoint of each edge. On hover, enlarge the label and increase opacity.

**Pros**:
- Makes edge semantics visible without needing the legend
- Particularly useful when `imports` and `inherits` edges connect the same pair of nodes
- Helps first-time users understand what the arrows mean

**Cons**:
- Adds visual clutter, especially when many edges are visible
- Sigma's built-in edge rendering doesn't natively support midpoint labels in WebGL
- Would require a custom canvas overlay or post-processing step

**Implications**:
- A hover-only approach avoids clutter — labels appear only when the user's mouse is near an edge
- Could use the edge color as background for the label chip to reinforce the color coding
- Need to handle label placement for curved or overlapping edges

**Opportunities**:
- Could show the import path (e.g., `from orders import create_order`) in a tooltip
- Could show edge weight or frequency if that data becomes available
- Clicking an edge label could select both endpoints and show the relationship in the sidebar

---

### 8. Notification Toasts for Key Events

**Idea**: Transient toast notifications that pop up at the top of the graph area when important events occur: agent errors, rewrite proposals ready, human input needed, discovery complete.

**How it works**: A fixed-position container at the top of `#graph-container`. On key SSE events, append a toast element with a message, type-colored left border, and auto-dismiss after 5 seconds. Click to dismiss immediately or navigate to the relevant node.

**Pros**:
- Events panel is easy to miss when focused on the graph — toasts demand attention
- Provides a bridge between background activity and user awareness
- Clickable toasts create a natural path from notification to action

**Cons**:
- Too many toasts at once (e.g., during bulk discovery) creates a toast storm
- Toasts floating over the graph can obscure important nodes
- Need careful rate-limiting to avoid overwhelming the user

**Implications**:
- Should only toast for "actionable" events: `human_input_request`, `rewrite_proposal`, `agent_error`, not for routine events like `agent_start`/`agent_complete`
- Toast container needs `pointer-events: none` except on the toast elements themselves
- Auto-dismiss timeout should be configurable (or extend on hover)

**Opportunities**:
- Toasts could include quick-action buttons (e.g., "Review Proposal" → opens the sidebar for that node)
- Could aggregate: "3 agents completed" instead of 3 separate toasts
- Sound/vibration option for `human_input_request` (opt-in, for demo presentations)

---

### 9. Split-Pane Source Viewer

**Idea**: When a node has a pending rewrite proposal, show a side-by-side diff view inside the sidebar: original source on the left, proposed rewrite on the right, with deletions/additions highlighted.

**How it works**: Fetch `/api/proposals/{node_id}/diff` and render a unified or side-by-side diff. The existing `renderSimpleDiff` function already does basic line-by-line diffing — enhance it with syntax highlighting and side-by-side layout.

**Pros**:
- The current diff view is basic pre-formatted text — a proper diff viewer dramatically improves readability
- The rewrite proposal workflow is a key Remora differentiator — it deserves polished UI
- Side-by-side is the standard for code review (GitHub, GitLab)

**Cons**:
- A proper diff viewer is complex (word-level diffing, syntax highlighting, scrollbar sync)
- The sidebar is 440px wide — side-by-side may be too cramped; may need a full-screen modal
- Would need a lightweight diff library or a more sophisticated custom renderer

**Implications**:
- Could use a modal overlay instead of cramming into the sidebar
- Line numbers should be visible for both old and new versions
- Accept/reject buttons should be prominently placed in the diff view

**Opportunities**:
- Could support partial acceptance (accept some hunks, reject others)
- Could show a "confidence" indicator for each change
- Natural path toward a "proposal queue" view showing all pending proposals across all agents

---

### 10. Node Grouping / Collapse

**Idea**: Allow collapsing a file column or directory bounding box into a single aggregate node, reducing visual complexity. The aggregate node shows the count of contained nodes and their collective status.

**How it works**: Clicking a directory box header or a collapse button converts all nodes in that group to hidden and replaces them with a single summary node. Clicking again expands back to the full view.

**Pros**:
- Essential for large codebases where not every file column is relevant
- Reduces cognitive load when the user wants to focus on a specific part of the graph
- The bounding box system already provides the grouping structure

**Cons**:
- Collapsed groups need to show aggregate edge information (e.g., "3 imports from this group")
- State management: which groups are collapsed needs to persist across graph refreshes
- The deterministic layout shifts when groups are collapsed — positions change

**Implications**:
- Collapsed aggregate nodes need a distinct visual style (e.g., folder icon, count badge)
- Edges to/from collapsed groups need to be re-routed to the aggregate node
- Could break the determinism guarantee if collapse state is interactive-only

**Opportunities**:
- Could default to collapsed for directories with no active agents
- Could use expand-on-hover for a quick peek without permanent state change
- Natural evolution toward a "focus mode" that collapses everything except the selected node's neighborhood

---

### 11. Semantic Search Integration

**Idea**: Wire the existing `/api/search` endpoint into the UI as a search modal. Users type a natural-language query, results are highlighted on the graph, and clicking a result zooms to that node.

**How it works**: A modal triggered by `Ctrl+Shift+F` or a search icon. Send the query to `/api/search` with mode `hybrid`. Results come back with node IDs and relevance scores. Highlight matching nodes on the graph with a glow effect and dim non-matches.

**Pros**:
- The search backend already exists and supports vector, fulltext, and hybrid search
- Natural-language search ("find the discount calculation") is much more powerful than name filtering
- Differentiates Remora from tools that only support syntactic search

**Cons**:
- Requires the search service to be configured (`uv sync --extra search` + Embeddy)
- Search results may not map 1:1 to graph nodes (search could return code chunks, not node IDs)
- Latency: vector search is slower than client-side filtering

**Implications**:
- Need graceful degradation when search is not configured (hide the button, show a setup hint)
- Results should show relevance scores and matched snippets
- The search modal should distinguish between "search nodes" and "search code" results

**Opportunities**:
- Could power a "related nodes" feature: select a node, search for semantically similar code
- Could feed into a "dependency explorer" that finds all code related to a concept
- The search API already returns `elapsed_ms` — show it for transparency

---

### 12. Dark/Light Theme Toggle

**Idea**: A toggle button that swaps the CSS custom properties between the current dark palette and a light palette.

**How it works**: Define a second set of CSS variables under a `.light` class on `:root`. Toggle the class on the document element. Persist the choice in `localStorage`.

**Pros**:
- Standard accessibility feature — some users strongly prefer light themes
- Simple to implement with CSS variables (the entire color system is already variable-based)
- Looks more professional in documentation and presentations

**Cons**:
- The Sigma canvas uses hardcoded colors in `drawNodeBoxLabel` and the `beforeRender` callback — these need to read from CSS variables or a JS theme object
- Node fill colors with alpha values need to be recalculated for light backgrounds
- Bounding box colors need different alpha values on light vs dark backgrounds

**Implications**:
- All canvas-drawn colors must be derived from the theme, not hardcoded
- The graph background color is set via Sigma's `backgroundColor` option — needs to be updated on toggle
- Edge colors need sufficient contrast on both light and dark backgrounds

**Opportunities**:
- Could support `prefers-color-scheme` media query for automatic detection
- A "high contrast" mode for presentations projected in bright rooms
- Theme could extend to the timeline, events panel, and agent panel

---

### 13. Responsive / Mobile Layout

**Idea**: On narrow viewports (< 768px), stack the sidebar below the graph instead of beside it. The graph gets the full viewport width, and the sidebar becomes a bottom sheet that can be swiped up.

**How it works**: CSS media query that changes the flex direction from `row` to `column`. The sidebar becomes a fixed-height panel at the bottom with a drag handle to expand. The graph container shrinks vertically to accommodate.

**Pros**:
- Makes the web UI usable on tablets and phones during presentations or field work
- The graph is the primary view — giving it full width on mobile is the right trade-off
- No JavaScript changes needed for the basic layout shift

**Cons**:
- Touch interaction with Sigma (pinch-zoom, pan) may conflict with system gestures
- The sidebar content (events, timeline, agent panel) is dense — cramming it into a bottom sheet is challenging
- Node labels may be too small to read on mobile without zooming

**Implications**:
- Filter chips need to wrap or scroll horizontally on narrow screens
- Touch targets need to be at least 44px per Apple HIG
- The companion panel is already complex on desktop — may need to be hidden on mobile

**Opportunities**:
- A "kiosk mode" that hides the sidebar entirely for display/monitoring purposes
- PWA manifest for installable app experience
- QR code on the graph page linking to the same URL for phone access during demos

---

### 14. Event Stream Filtering

**Idea**: Add filter buttons above the events panel to show/hide events by type. Quick toggles for: agent events, node events, system events, errors only.

**How it works**: Wrap each event line in a span with a `data-event-type` attribute. Toggle CSS `display` based on active filters. Store filter state in a `Set`.

**Pros**:
- The current events panel quickly fills with noise during active discovery/execution
- Filtering by type lets users focus on what matters (e.g., "show me only errors")
- Simple DOM-based filtering, no re-fetching needed

**Cons**:
- Adding HTML attributes to every event line increases DOM size
- Filter UI adds visual complexity to an already-dense sidebar
- Need to decide on event categories (how to group 20+ event types into 3-4 filters)

**Implications**:
- Natural grouping: `agent_*` → Agent, `node_*` → Node, `rewrite_*` → Proposal, `*error*` → Error
- Could use the same chip UI pattern as the graph filter bar for consistency
- Should persist filter state across event stream updates

**Opportunities**:
- Could add a "pause" button that freezes the event stream for reading
- Could add event count badges on each filter chip
- Export filtered events as JSON for debugging

---

### 15. Connection Quality Indicator

**Idea**: Expand the current `●` connection indicator into a richer status display showing SSE health: connected/disconnected, last event timestamp, reconnect count.

**How it works**: Track `lastEventTimestamp`, `reconnectCount`, and `connectionUptime` in JS. Display as a hover tooltip on the status indicator. Change the indicator color based on freshness: green (< 5s since last event), yellow (5-30s), red (disconnected).

**Pros**:
- The current indicator is binary (connected/disconnected) — doesn't show staleness
- Helps diagnose issues: "I'm connected but no events are arriving"
- Reconnect count reveals flaky connections

**Cons**:
- Adds complexity for a feature most users won't need
- "Time since last event" can be misleading when nothing is happening (idle system looks stale)
- Tooltip content needs to update on a timer

**Implications**:
- Should distinguish "no events because idle" from "no events because broken"
- Could use the SSE `id` field to detect gaps in event sequence
- The `Last-Event-ID` header on reconnect already handles replay — this is purely UI

**Opportunities**:
- Could show a "replay from..." button when reconnecting with a gap
- Could log connection history for post-mortem debugging
- Could trigger an automatic `loadGraph()` refresh after a reconnect to resync state

---

### 16. Breadcrumb Trail for Node Context

**Idea**: When a node is selected, show a breadcrumb trail above the node details: `src/ > services/ > orders.py > OrderRequest > create_order`. Each segment is clickable to zoom to that level.

**How it works**: Walk the `parent_id` chain from the selected node to the root. Render each ancestor as a breadcrumb segment. Clicking a directory segment zooms the camera to its bounding box. Clicking a file segment centers on that file's column.

**Pros**:
- Provides instant spatial context for the selected node
- Clickable breadcrumbs enable hierarchical navigation
- The `parent_id` chain and `file_path` data already exist in the node model

**Cons**:
- Breadcrumbs can be long for deeply nested nodes (5+ levels)
- Directories are not graph nodes — clicking a directory breadcrumb needs to zoom to the bounding box, not select a node
- Takes vertical space in the already-dense sidebar

**Implications**:
- Should truncate with `...` for very deep paths, expanding on hover
- The bounding box map (`boundingBoxes`) provides zoom targets for directory levels
- Could replace the current `File: path:line-line` text in node details

**Opportunities**:
- Could show a small inline status icon per breadcrumb level (e.g., if the parent class has an error)
- Natural extension toward a tree-view sidebar mode (alternative to graph view)
- Could drive a "zoom to file" feature that centers on a file column and zooms to fit it

---

## Part II — Demo Showcase Ideas

---

### 17. Guided Walkthrough Mode

**Idea**: A scripted overlay that walks a new user through the Remora UI step by step. Each step highlights a UI element, explains what it does, and waits for the user to interact before advancing.

**How it works**: A JSON array of walkthrough steps, each specifying a target element selector, tooltip text, and optional action (e.g., "click this node"). A floating overlay darkens everything except the target. Next/Back buttons advance through steps.

**Pros**:
- Essential for first-time users and demos to non-technical audiences
- Shows the system's capabilities in a structured narrative
- Can be reused for documentation screenshots and video scripts

**Cons**:
- Walkthrough scripts are brittle — UI changes break step selectors
- Building a tutorial overlay system is substantial engineering effort
- Forced linear progression doesn't match how real users explore

**Implications**:
- Could use a lightweight library like Shepherd.js or build a minimal custom solution
- Steps need to account for async state (wait for discovery to complete, wait for agent to start)
- Should be dismissable at any point ("Skip tour")

**Opportunities**:
- Could generate walkthrough steps from a markdown script for easy authoring
- Could record user interactions during the walkthrough for analytics
- Multiple walkthrough tracks: "Quick Overview" (2 min), "Deep Dive" (10 min), "Developer Guide" (20 min)

---

### 18. Live Coding Trigger

**Idea**: During a demo, open an editor (or simulate an edit) and modify a file in the watched project. Remora detects the change, re-discovers nodes, and agents react — all visible in real time on the graph.

**How it works**: Remora already watches the filesystem via its watcher subsystem. Edit a Python file (e.g., add a new function, modify an existing one). The `content_changed` event triggers re-discovery → `node_discovered`/`node_changed` SSE events → graph updates → agent reactions.

**Pros**:
- This IS the core Remora value proposition — showing it live is the most compelling demo
- Demonstrates the reactive loop: edit → discover → analyze → propose
- Audience sees the graph morph in real time — powerful visual

**Cons**:
- Live coding is unpredictable — typos, unexpected agent behavior, slow LLM responses
- Requires a running LLM backend (or mock) for agents to actually react
- Timing is hard to control in a live demo setting

**Implications**:
- Should have a pre-written edit (copy-paste a prepared change) rather than typing live
- Need a fast LLM or mock responses for predictable demo timing
- The graph animation for `node_discovered` (full re-layout via `loadGraph()`) can be jarring if many nodes shift

**Opportunities**:
- Could pre-record a script of file edits and replay them with `setTimeout` for a deterministic demo
- Could show a split screen: editor on left, graph on right
- Could use the `cursor_focus` endpoint to show the cursor tracking as the edit happens

---

### 19. Multi-Agent Collaboration Scenario

**Idea**: A demo scenario where multiple agents interact: a code agent proposes a change, a review agent catches an issue, the code agent revises, and the review agent approves.

**How it works**: Set up the demo project with:
1. A code agent on a function with a subtle bug
2. A review agent configured to review changes
3. Trigger the code agent to propose a rewrite
4. The review agent reacts to `content_changed`, finds the issue, sends a message
5. The code agent responds with a revision

**Pros**:
- Demonstrates the multi-agent architecture — Remora's key differentiator
- Shows the event-driven reactive loop between agents
- The review-agent bundle already exists in `defaults/bundles/review-agent`

**Cons**:
- Multi-agent interaction is hard to script reliably — agents may not produce expected output
- Requires the LLM to generate appropriate responses for both agents
- Timing is unpredictable — the demo may stall waiting for LLM responses

**Implications**:
- Should use a capable model (not just Qwen3-4B) for reliable multi-agent behavior
- May need mock/recorded responses for a reliable demo
- The graph should visually show the interaction: agent A turns orange → agent B turns orange → messages flow

**Opportunities**:
- Could add visual "message arrows" between agents when `agent_message` events flow
- Could highlight the causal chain: "this agent started because that agent changed this file"
- Could show a timeline view that makes the interaction sequence clear

---

### 20. Human-in-the-Loop Showcase

**Idea**: A demo where an agent reaches a decision point and asks for human input via the `human_input_request` event. The presenter responds through the web UI chat input, and the agent continues.

**How it works**: Configure an agent with a prompt that asks for clarification when encountering ambiguity. When `human_input_request` fires:
1. The node turns yellow (awaiting_input)
2. A toast notification appears
3. The presenter clicks the node, sees the question in the agent panel
4. Types a response in the chat input
5. The agent continues with the response

**Pros**:
- Demonstrates that Remora agents are not autonomous black boxes — humans stay in the loop
- The UI already supports this workflow (chat input, human_input_request rendering)
- Highly interactive — engages the demo audience

**Cons**:
- Depends on the agent actually generating a human_input_request (needs prompt engineering)
- The presenter needs to type a coherent response on the spot
- If the agent doesn't ask the right question, the demo falls flat

**Implications**:
- Should have a pre-planned question and response for the demo
- The node status animation (idea #3) would make this much more visible
- Toast notifications (idea #8) would make the request impossible to miss

**Opportunities**:
- Could show multiple input modalities: text response, option selection, approval/rejection
- Could demonstrate the `options` field in `human_input_request` for structured choices
- Natural segue into the rewrite proposal workflow (idea #21)

---

### 21. Rewrite Proposal Workflow

**Idea**: A demo that culminates in a rewrite proposal: an agent analyzes code, proposes changes, the user reviews the diff, and accepts or rejects.

**How it works**:
1. An agent runs on a function that needs improvement
2. The agent proposes a rewrite (`rewrite_proposal` event)
3. The node turns yellow (awaiting_review)
4. The presenter clicks "View Diff" → sees the proposed changes
5. Clicks "Accept" → the code materializes on disk → `content_changed` event
6. The graph reflects the change

**Pros**:
- End-to-end demonstration of Remora's core workflow
- The proposal/review/accept cycle is concrete and understandable
- All the infrastructure already exists (proposals API, diff viewer, accept/reject endpoints)

**Cons**:
- Requires the LLM to produce a valid, meaningful rewrite proposal
- The current diff viewer is basic — needs improvement (see idea #9)
- Acceptance writes to disk — need to ensure the demo project is disposable

**Implications**:
- Should use a demo project where the proposed change is obviously beneficial (e.g., fix a clear bug)
- The diff should be small and understandable (2-5 lines changed, not a full rewrite)
- After acceptance, the graph should show `content_changed` cascading to other agents

**Opportunities**:
- Could show rejection + feedback: reject with a reason, agent revises based on feedback
- Could demonstrate partial acceptance if that feature is built
- Could show before/after source side-by-side (idea #25)

---

### 22. Graph Evolution Replay

**Idea**: Record the full sequence of SSE events during a demo run, then replay them to show the graph building up from empty to fully populated. Like a time-lapse of the system coming alive.

**How it works**: During a live run, capture all events to a JSON file (timestamp, event_type, payload). For replay, read the file, compute relative timestamps, and feed events to the SSE handler functions at the original pace (or accelerated).

**Pros**:
- Deterministic and repeatable — no live LLM needed
- Shows the discovery and agent activation sequence as a narrative
- Can be sped up (2x, 5x) for presentations or slowed down for explanation

**Cons**:
- Requires building a replay mechanism (event injection into the SSE handler)
- The graph re-layout on each `node_discovered` event may produce jarring jumps during replay
- Replayed events don't match live API state — clicking a node during replay may show stale data

**Implications**:
- The SSE endpoint supports `replay=N` for the last N events — could extend this for full replay
- Need to decide whether replay drives the graph from empty or from a checkpoint
- The timeline panel naturally shows the replay sequence

**Opportunities**:
- Could become a first-class "demo mode" accessible via URL parameter: `?replay=recording.json`
- Could support annotations: "At this point, the review agent noticed a bug..."
- Could power automated regression testing of the UI (compare snapshots at key moments)

---

### 23. Cursor-Following Demo (LSP)

**Idea**: Show the LSP companion integration: as the presenter moves their cursor in Neovim/VS Code, the web UI tracks the cursor position, highlights the corresponding node, and shows source context in the companion panel.

**How it works**: The LSP sends `cursor_focus` events via the `/api/cursor` endpoint. The web UI receives them via SSE, highlights the node, animates the camera to it, and populates the companion panel with the node's source.

**Pros**:
- Demonstrates the editor ↔ web UI integration — a unique Remora capability
- The companion panel (`#companion-panel`) and cursor_focus handler already exist
- Visually impressive: the graph "follows" the cursor as if the editor and graph are linked

**Cons**:
- Requires a working LSP integration (pygls + editor plugin)
- Screen real estate: need to show both the editor and the web UI simultaneously
- Cursor focus events fire rapidly — need debouncing to avoid graph jitter

**Implications**:
- Best shown with a split-screen setup or a second monitor
- The camera animation on cursor_focus (`camera.animate`) should be smooth and not jarring
- Should show nodes that the cursor leaves returning to normal (current code already does this via size reset)

**Opportunities**:
- Could add a "file outline" sidebar mode that shows all nodes in the current file
- Could show "cursor heatmap" data — which nodes the developer spends most time in
- Could trigger agent analysis when the cursor lingers on a node for > 5 seconds

---

### 24. Scale Stress Test

**Idea**: Run Remora on a larger codebase (50-100 files, 200+ nodes) to demonstrate that the graph layout and UI remain usable at scale.

**How it works**: Prepare a real-world project (or synthetic codebase) with enough files and classes to stress the layout. Run Remora, open the web UI, and demonstrate that:
1. The column layout remains readable
2. Bounding boxes nest properly
3. Search and filtering are essential at this scale
4. Node grouping/collapse (idea #10) becomes critical

**Pros**:
- Proves the system works beyond toy demos
- Identifies real performance bottlenecks before users hit them
- Forces the UI to justify its design decisions (is the column layout still readable at 50 columns?)

**Cons**:
- At 200+ nodes, the current graph will likely have performance issues (canvas rendering, layout computation)
- May expose UX problems that are hard to fix (too many columns, labels too small to read)
- Requires a representative codebase that's complex enough but still understandable for a demo

**Implications**:
- The `loadGraph()` full re-layout on every `node_discovered` event will be expensive at scale
- May need incremental layout (position only new nodes, keep existing positions stable)
- Minimap (idea #1) and search (idea #2) become essential, not optional

**Opportunities**:
- Could establish performance benchmarks: "renders 200 nodes in < 100ms"
- Could identify which features to implement first for scale (grouping, search, minimap)
- Could lead to a "progressive loading" strategy: show most-relevant nodes first, load others on demand

---

### 25. Before/After Comparison

**Idea**: Side-by-side screenshots showing the graph before and after an agent makes changes. The structural difference (new nodes, changed edges, status transitions) is immediately visible.

**How it works**: Capture a graph snapshot (idea #5) before triggering an agent. After the agent completes (proposal accepted, code changed), capture another snapshot. Display them side by side in a presentation or the UI itself.

**Pros**:
- Static comparison is easier to present than live animation
- Clearly shows the value agents provide (before: bug, after: fix)
- Can be generated automatically during CI for documentation

**Cons**:
- Requires the snapshot/export feature (idea #5) to exist first
- Layout shift between snapshots may obscure the actual change (node positions move because new nodes were added)
- Only captures visual state — the important change may be in the code, not the graph

**Implications**:
- The deterministic layout is critical here — minimizing layout shift between snapshots
- Should highlight the changed nodes (e.g., green glow on modified nodes in the "after" view)
- Could use the `content_changed` event to identify which nodes changed

**Opportunities**:
- Could generate animated transitions between before/after (morph the graph)
- Could produce a "change summary" view: "Agent modified 3 functions, added 1 class, proposed 2 rewrites"
- Natural material for blog posts, documentation, and marketing

---

### 26. Error Recovery Demo

**Idea**: Deliberately trigger an agent error (e.g., invalid tool call, LLM timeout, permission denied) and demonstrate the system's resilience: the error state is visible, the user can inspect the error, and the agent recovers.

**How it works**:
1. Configure an agent with a prompt that causes a predictable error
2. The `agent_error` event fires → node turns red
3. The presenter clicks the node → sees the error in the agent panel
4. The agent's status transitions back to idle (or the presenter manually retries)
5. On retry, the agent succeeds

**Pros**:
- Shows that errors are visible and recoverable, not silent failures
- Demonstrates the status transition system: running → error → idle → running → complete
- Builds trust: "the system fails gracefully"

**Cons**:
- Deliberately causing errors feels artificial in a demo
- The recovery mechanism depends on what caused the error — may not be simple to demonstrate
- Error messages from LLMs can be cryptic and hard to explain to a demo audience

**Implications**:
- Best paired with a retry button in the agent panel (if one doesn't exist, add it)
- The error state animation (idea #3) would make the error node visually striking
- Should show the error in the events panel and timeline for correlation

**Opportunities**:
- Could demonstrate dead-letter handling: "this error was logged and will be retried automatically"
- Could show the agent's conversation history leading up to the error for debugging
- Could demonstrate graceful degradation: "one agent failed but the rest of the system continued"

---

## Priority Matrix

| Idea | Impact | Effort | Depends On | Recommended Phase |
|------|--------|--------|------------|-------------------|
| **3 — Status Animation** | High | Low | Nothing | Phase 1 (Quick wins) |
| **8 — Toast Notifications** | High | Low | Nothing | Phase 1 |
| **16 — Breadcrumb Trail** | Medium | Low | Nothing | Phase 1 |
| **14 — Event Filtering** | Medium | Low | Nothing | Phase 1 |
| **2 — Search Bar** | High | Medium | Nothing | Phase 2 (Core UX) |
| **4 — Conversation Drawer** | High | Medium | Nothing | Phase 2 |
| **6 — Keyboard Navigation** | Medium | Medium | Nothing | Phase 2 |
| **15 — Connection Indicator** | Low | Low | Nothing | Phase 2 |
| **1 — Minimap** | Medium | Medium | Nothing | Phase 3 (Polish) |
| **5 — Snapshot Export** | Medium | Medium | Nothing | Phase 3 |
| **7 — Edge Labels** | Low | Medium | Nothing | Phase 3 |
| **9 — Split-Pane Diff** | High | High | Nothing | Phase 3 |
| **12 — Dark/Light Toggle** | Medium | Medium | Nothing | Phase 3 |
| **10 — Node Grouping** | High | High | Nothing | Phase 4 (Advanced) |
| **11 — Semantic Search** | High | Medium | Search service | Phase 4 |
| **13 — Responsive Layout** | Low | Medium | Nothing | Phase 4 |
| **21 — Proposal Workflow Demo** | High | Low | Working agents | Demo Phase 1 |
| **18 — Live Coding Trigger** | High | Low | Working watcher | Demo Phase 1 |
| **20 — Human-in-the-Loop** | High | Medium | #3, #8 | Demo Phase 1 |
| **26 — Error Recovery** | Medium | Low | #3 | Demo Phase 1 |
| **17 — Guided Walkthrough** | High | High | All Phase 1-2 UI | Demo Phase 2 |
| **19 — Multi-Agent Collab** | High | High | Working agents | Demo Phase 2 |
| **22 — Graph Replay** | Medium | High | Nothing | Demo Phase 2 |
| **23 — Cursor Following** | High | Medium | Working LSP | Demo Phase 2 |
| **24 — Scale Stress Test** | Medium | Medium | #1, #2, #10 | Demo Phase 3 |
| **25 — Before/After** | Medium | Medium | #5 | Demo Phase 3 |
