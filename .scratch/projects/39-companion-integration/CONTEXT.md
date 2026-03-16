# Context — Companion Integration

## Current State
Implementation has started from `IMPLEMENTATION_GUIDE.md`.

Completed:
- Step 1: Added `TurnDigestedEvent` to the event system.
  - Updated `src/remora/core/events/types.py` with new event model and export.
  - Updated `src/remora/core/events/__init__.py` exports.
  - Extended `tests/unit/test_events.py` with default/full/envelope coverage and instantiation coverage.
  - Verification: `devenv shell -- pytest tests/unit/test_events.py -q` (11 passed).
- Step 2: Added tag-based turn classification in actor completion flow.
  - `AgentTurnExecutor.execute_turn()` now classifies completion as:
    - `("primary",)` for normal turns
    - `("reflection",)` when triggered by `AgentCompleteEvent` tagged `primary`
  - `_complete_agent_turn()` now accepts `turn_tags` and emits them on `AgentCompleteEvent`.
  - Added actor tests for primary/reflection tagging in `tests/unit/test_actor.py`.
  - Verification: `devenv shell -- pytest tests/unit/test_actor.py -q` (31 passed).
- Step 3: Enriched `AgentCompleteEvent` with `user_message`.
  - Added `user_message: str = ""` to `AgentCompleteEvent` in `src/remora/core/events/types.py`.
  - `AgentTurnExecutor.execute_turn()` now captures user prompt content and passes it to completion emission.
  - `_complete_agent_turn()` now accepts `user_message` and includes it in emitted `AgentCompleteEvent`.
  - Added event-model and actor emission tests for `user_message`.
  - Verification: `devenv shell -- pytest tests/unit/test_events.py tests/unit/test_actor.py -q` (46 passed).
- Step 4: Added exclusion filter support to subscriptions.
  - Added `not_from_agents` to `SubscriptionPattern`.
  - `SubscriptionPattern.matches()` now excludes matching `agent_id` or `from_agent`.
  - Added pattern and registry tests for `not_from_agents` behavior in `tests/unit/test_subscription_registry.py`.
  - Verification: `devenv shell -- pytest tests/unit/test_subscription_registry.py -q` (16 passed).
- Step 5: Added KV-native companion tools.
  - Added system tools:
    - `bundles/system/tools/companion_summarize.pym`
    - `bundles/system/tools/companion_reflect.pym`
    - `bundles/system/tools/companion_link.pym`
  - Added `tests/unit/test_companion_tools.py` for presence/content checks.
  - Verified Grail parsing compatibility with existing tool test suites.
  - Verification:
    - `devenv shell -- pytest tests/unit/test_companion_tools.py tests/unit/test_system_tools.py tests/unit/test_grail.py -q` (21 passed)
- Step 6: Added self-reflect subscription registration.
  - `FileReconciler._register_subscriptions()` now checks workspace KV `_system/self_reflect`.
  - When enabled, it registers a self-subscription:
    - `event_types=["AgentCompleteEvent"]`
    - `from_agents=[node.node_id]`
    - `tags=["primary"]`
  - Updated `SubscriptionPattern.from_agents` matching to support both `from_agent` and `agent_id` event shapes.
  - Added reconciler tests for self-reflect enabled/disabled subscription behavior.
  - Verification:
    - `devenv shell -- pytest tests/unit/test_reconciler.py tests/unit/test_subscription_registry.py -q` (36 passed)
- Step 7: Parsed and persisted `self_reflect` config.
  - `Actor._read_bundle_config()` now parses optional `self_reflect` dict (`enabled`, `model`, `max_turns`, `prompt`) with validation/coercion.
  - `FileReconciler._provision_bundle()` now syncs `_system/self_reflect` in workspace KV based on bundle config.
  - Added actor tests for parsing enabled/disabled self_reflect.
  - Added reconciler tests for KV persistence/clearing of self_reflect config.
  - Verification:
    - `devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_reconciler.py -q` (56 passed)
- Step 8: Reflection override in `PromptBuilder`.
  - Added `_DEFAULT_REFLECTION_PROMPT` in `src/remora/core/actor.py`.
  - `PromptBuilder.build_system_prompt()` now detects reflection triggers (`AgentCompleteEvent` with `primary` tag and enabled `self_reflect`) and overrides:
    - system prompt
    - model
    - max_turns
  - Added prompt-builder tests for reflection override, normal behavior, and tag gating.
  - Verification: `devenv shell -- pytest tests/unit/test_actor.py -q` (37 passed)
- Step 9: Companion context injection into system prompt.
  - Added `AgentTurnExecutor._build_companion_context(workspace)` in `src/remora/core/actor.py`.
  - Primary turns now append companion context from KV (`companion/reflections`, `companion/chat_index`, `companion/links`) to the system prompt.
  - Reflection turns do not inject companion context.
  - Added tests for context building and prompt injection behavior in `tests/unit/test_actor.py`.
  - Verification: `devenv shell -- pytest tests/unit/test_actor.py -v -k companion_context` (4 passed).
- Step 10: Added self-reflect config to code-agent bundle.
  - Updated `bundles/code-agent/bundle.yaml` with a `self_reflect` section (`enabled`, `model`, `max_turns`, `prompt`).
  - Added `tests/unit/test_bundle_configs.py` for bundle self-reflect config validation.
  - Verification: `devenv shell -- pytest tests/unit/test_bundle_configs.py -v` (1 passed).
- Step 11: Added web companion API endpoint.
  - Added `GET /api/nodes/{node_id}/companion` in `src/remora/web/server.py`.
  - Endpoint returns workspace KV data for `companion/chat_index`, `companion/reflections`, `companion/links`.
  - Added web tests in `tests/unit/test_web_server.py` for empty and populated companion data responses.
  - Verification: `devenv shell -- pytest tests/unit/test_web_server.py -v -k companion` (2 passed).
- Step 12: Added Layer 2 companion observer bundle.
  - Added `bundles/companion/bundle.yaml` with project-level observer prompt and reactive trigger handling for `TurnDigestedEvent`.
  - Added `bundles/companion/tools/aggregate_digest.pym` to maintain project activity/tag/agent/insight KV keys.
  - Extended `tests/unit/test_companion_tools.py` with bundle/tool existence and content checks.
  - Verification: `devenv shell -- pytest tests/unit/test_companion_tools.py -v` (5 passed).

## Notes
- Pydantic emits a warning for `TurnDigestedEvent.summary` because `Event` also has a `summary()` method; behavior is correct and tests pass.

## Next Step
- Step 13: Add companion system Layer 2 example config comments to `remora.yaml.example` and validate YAML.
