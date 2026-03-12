# Assumptions

## What Remora Is
- General-purpose **event-driven graph agent runner**
- Code (tree-sitter CST nodes) is the primary, always-present plugin — not optional, but cleanly separated from the core engine
- Users write agents as Grail `.pym` scripts; the Python library is the substrate

## Core Invariants
- Every node is a code node (CodeNode): has source_code, file_path, start_line, end_line, caller/callee ids
- Nodes always link back to tree-sitter-parsed source
- We like types — no metadata blobs for code-specific data
- Cairn workspaces are core: every agent node has its own persistent Cairn workspace

## Agent Config
- `bundle.yaml` stays — it's plain text, so agents can read/modify their own config
- Agents can evolve their own system_prompt by writing to their bundle.yaml

## Host Modes
- One AgentRunner handles all host modes
- Web UI (localhost HTTP + SSE) is the primary UX surface for companion mode and graph visualization
- LSP/Neovim is an optional thin adapter (translates LSP → events), not a required host
- No special "headless vs LSP" execution paths

## Execution Model
- Trigger → AgentRunner → Cairn workspace → load .pym tools → LLM turn → emit events
- All agent behaviors (rewrite_self, message_node, subscribe, summarize, etc.) are `.pym` tools
- The Python library provides externals; .pym scripts define what agents do with them

## Grail Externals Strategy
- Base externals: Cairn workspace ops (read/write/list/search files) + graph ops + event ops
- Code plugin adds: rewrite_node, get_node_source
- This is the entire API surface between Python and agent logic
