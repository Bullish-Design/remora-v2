# CONTEXT

Working on first-pass distillation of Remora v2 into Allium.

Current state:
- Required rules loaded from `.scratch/CRITICAL_RULES.md` and `.scratch/REPO_RULES.md`.
- Core behavior extracted from:
  - `src/remora/code/reconciler.py`
  - `src/remora/code/directories.py`
  - `src/remora/code/virtual_agents.py`
  - `src/remora/core/events/*`
  - `src/remora/core/agents/*`
  - `src/remora/core/tools/capabilities.py`
  - `src/remora/core/services/lifecycle.py`
- Dependency behavior cross-checked from `.context/`:
  - `structured-agents_v0.4.0/src/structured_agents/events/types.py`
  - `structured-agents_v0.4.0/src/structured_agents/kernel.py`
  - `cairn/src/cairn/runtime/workspace_manager.py`
- Distilled spec created:
  - `.scratch/projects/56-remora-runtime-allium-distillation/remora-runtime.allium`
  - `specs/remora-runtime.allium` (canonical copy)

Next:
- Review/iterate the spec with user-selected scope expansion:
  - Split out library specs (e.g., model/tool execution surface).
  - Add deeper surface/contract blocks if required.
