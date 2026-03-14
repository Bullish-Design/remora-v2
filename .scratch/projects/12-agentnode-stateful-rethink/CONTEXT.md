# Context

## Current Status
All 12 PRs in `REFACTORING_GUIDE.md` are implemented, committed, and pushed.
Unit/integration test suite is green: `201 passed, 1 skipped`.

## Completed Work Summary
1. Unified user/system messaging on `AgentMessageEvent`.
2. Removed `AgentTextResponse`.
3. Added chat/reactive turn modes with prompt injection.
4. Added bundle `prompts.chat`/`prompts.reactive`.
5. Removed stable workspace fallback.
6. Moved companion tools into system bundle; removed companion bundle.
7. Made bundle config additive over system base; merged bundle yaml overlays.
8. Removed manual logging preview helpers.
9. Exposed KV APIs through workspace, turn context, and system tools.
10. Added `Event.to_envelope()` and envelope-based event payload persistence path.
11. Renamed major runtime concepts:
   - `CodeNode`→`Node`, `CodeElement`→`DiscoveredElement`
   - `AgentActor`→`Actor`, `AgentContext`→`TurnContext`, `AgentRunner`→`ActorPool`
   - `bundle_name`→`role`, `swarm_root`→`workspace_root`
   - `to_externals_dict()`→`to_capabilities_dict()`
   Compatibility aliases were retained where needed.
12. Hardened runtime `_bundle/bundle.yaml` loading against malformed YAML and invalid shapes; documented bundle files as runtime-mutable.

## Next Step
Project implementation is complete; no pending PR items remain in this project plan.
