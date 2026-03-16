# TEST_SUIDE_FAILURE_REPORT

## Scope
- Analyzed the full suite run from: `devenv shell -- pytest tests/ -q --tb=short --junitxml=/tmp/pytest_full.xml`
- Run timestamp: `2026-03-16T16:40:01.978112-04:00`
- Total tests: `355` | failures: `25` | errors: `123` | skipped: `8` | duration: `107.502s`

## Executive Summary
- The failures are dominated by **resource exhaustion** (`Too many open files`), which cascades into sqlite/workspace/open failures.
- There is one **real semantic test mismatch** introduced by companion work: a legacy test still asserts that `bundles/companion` must not exist.
- Because of resource exhaustion, many failing tests are likely secondary and must be re-evaluated after FD-leak remediation.

## Root Cause Categories
| Category | Count | What it means |
|---|---:|---|
| `FILE_DESCRIPTOR_EXHAUSTION` | 5 | Direct `OSError: [Errno 24] Too many open files` failures. |
| `GRAIL_DISCOVERY_ASSERTION_SECONDARY_TO_FD_PRESSURE` | 1 | Assertion failure caused by Grail tool discovery returning empty after FD exhaustion. |
| `SQLITE_OPEN_DB_FAILURE_FROM_FD_PRESSURE` | 139 | Setup/runtime failures opening sqlite DB files (`unable to open database file`) after FD exhaustion. |
| `WORKSPACE_OPEN_FAILED_FROM_FD_PRESSURE` | 1 | Cairn workspace open failed during perf test (downstream of FD pressure). |
| `LSP_ACCEPTANCE_TIMEOUT_UNDER_RESOURCE_PRESSURE` | 1 | Acceptance LSP init timed out (likely resource pressure side effect). |
| `STALE_COMPANION_TEST_EXPECTATION` | 1 | Legacy assertion conflicts with new companion bundle introduction. |

## Detailed Findings and Proposed Fixes
### FILE_DESCRIPTOR_EXHAUSTION
- Affected tests: `5`
- Explanation: Direct `OSError: [Errno 24] Too many open files` failures.
- Proposed fixes:
  - Primary fix: identify and close leaked file/log/database handles between tests (especially logging handlers and workspace/db resources).
  - Add an autouse pytest fixture to close and detach `logging` handlers after each test module/session where startup paths are exercised.
  - Audit lifecycle teardown paths (`services.stop()`, actor pool shutdown, workspace close) for deterministic close behavior.
  - Add a focused regression test that runs repeated startup/shutdown cycles and asserts FD count stays bounded.
- Affected test IDs:
  - `tests.unit.test_cli::test_cli_start_smoke`
  - `tests.unit.test_grail::test_grail_tool_error_handling`
  - `tests.unit.test_grail::test_grail_tool_execute`
  - `tests.unit.test_grail::test_grail_tool_execute_logs_start_and_failure`
  - `tests.unit.test_reconciler::test_reconciler_handles_external_paths`

### GRAIL_DISCOVERY_ASSERTION_SECONDARY_TO_FD_PRESSURE
- Affected tests: `1`
- Explanation: Assertion failure caused by Grail tool discovery returning empty after FD exhaustion.
- Proposed fixes:
  - Treat as downstream of FD exhaustion in temp file + logging path.
  - After FD fix, add targeted test for `discover_tools` resilience when one tool fails to load.
- Affected test IDs:
  - `tests.unit.test_grail::test_discover_tools_from_workspace`

### SQLITE_OPEN_DB_FAILURE_FROM_FD_PRESSURE
- Affected tests: `139`
- Explanation: Setup/runtime failures opening sqlite DB files (`unable to open database file`) after FD exhaustion.
- Proposed fixes:
  - Downstream of FD exhaustion; most setup fixtures cannot open sqlite connections once FD limit is hit.
  - After FD fix, rerun full suite to confirm these disappear without code changes in DB modules.
- Affected test IDs:
  - `tests.integration.test_startup_shutdown::test_startup_shutdown_path_runs_cleanly_for_two_seconds`
  - `tests.unit.test_actor::test_actor_chat_mode_injects_prompt`
  - `tests.unit.test_actor::test_actor_cooldown`
  - `tests.unit.test_actor::test_actor_depth_cleanup_removes_stale_entries`
  - `tests.unit.test_actor::test_actor_depth_limit`
  - `tests.unit.test_actor::test_actor_emits_kernel_observability_events`
  - `tests.unit.test_actor::test_actor_emits_primary_tag_on_normal_completion`
  - `tests.unit.test_actor::test_actor_emits_reflection_tag_on_self_completion_trigger`
  - `tests.unit.test_actor::test_actor_emits_user_message_on_completion`
  - `tests.unit.test_actor::test_actor_execute_turn_emits_error_event_on_kernel_failure`
  - `tests.unit.test_actor::test_actor_execute_turn_respects_shared_semaphore`
  - `tests.unit.test_actor::test_actor_execute_turn_retries_kernel_once`
  - `tests.unit.test_actor::test_actor_logging_preserves_newlines`
  - `tests.unit.test_actor::test_actor_logs_full_response_not_truncated`
  - `tests.unit.test_actor::test_actor_logs_model_request_and_response`
  - `tests.unit.test_actor::test_actor_missing_node`
  - `tests.unit.test_actor::test_actor_processes_inbox_message`
  - `tests.unit.test_actor::test_actor_reactive_mode_injects_prompt`
  - `tests.unit.test_actor::test_actor_reload_reads_updated_bundle_config_each_turn`
  - `tests.unit.test_actor::test_actor_reset_clears_depth_timestamp`
  - `tests.unit.test_actor::test_actor_start_stop`
  - `tests.unit.test_actor::test_build_companion_context_empty`
  - `tests.unit.test_actor::test_build_companion_context_with_data`
  - `tests.unit.test_actor::test_companion_context_injected_for_primary_turn`
  - `tests.unit.test_actor::test_companion_context_not_injected_for_reflection_turn`
  - `tests.unit.test_actor::test_outbox_correlation_id_setter`
  - `tests.unit.test_actor::test_outbox_emit_persists_event`
  - `tests.unit.test_actor::test_outbox_increments_sequence`
  - `tests.unit.test_actor::test_outbox_preserves_existing_correlation_id`
  - `tests.unit.test_actor::test_outbox_tags_correlation_id`
  - `tests.unit.test_actor::test_read_bundle_config_allows_env_override_for_placeholder`
  - `tests.unit.test_actor::test_read_bundle_config_expands_model_from_env_default`
  - `tests.unit.test_actor::test_read_bundle_config_ignores_disabled_self_reflect`
  - `tests.unit.test_actor::test_read_bundle_config_literal_model_overrides_env`
  - `tests.unit.test_actor::test_read_bundle_config_malformed_yaml_returns_empty`
  - `tests.unit.test_actor::test_read_bundle_config_parses_self_reflect`
  - `tests.unit.test_actor::test_turn_logs_include_correlation_id`
  - `tests.unit.test_db::test_asyncdb_execute_and_fetch`
  - `tests.unit.test_db::test_asyncdb_execute_many`
  - `tests.unit.test_db::test_asyncdb_fetch_all`
  - `tests.unit.test_db::test_asyncdb_insert_and_delete`
  - `tests.unit.test_event_store::test_eventstore_append_returns_id`
  - `tests.unit.test_event_store::test_eventstore_forwards_to_bus`
  - `tests.unit.test_event_store::test_eventstore_query_by_agent`
  - `tests.unit.test_event_store::test_eventstore_query_events`
  - `tests.unit.test_event_store::test_eventstore_trigger_flow`
  - `tests.unit.test_externals::test_capabilities_include_search_methods`
  - `tests.unit.test_externals::test_externals_broadcast_caps_target_count`
  - `tests.unit.test_externals::test_externals_broadcast_siblings_and_file_patterns`
  - `tests.unit.test_externals::test_externals_code_ops`
  - `tests.unit.test_externals::test_externals_communication`
  - `tests.unit.test_externals::test_externals_emit_uses_outbox_when_provided`
  - `tests.unit.test_externals::test_externals_event_ops`
  - `tests.unit.test_externals::test_externals_event_subscribe_supports_tag_filters`
  - `tests.unit.test_externals::test_externals_graph_get_children`
  - `tests.unit.test_externals::test_externals_graph_ops`
  - `tests.unit.test_externals::test_externals_graph_query_nodes_rejects_invalid_enums`
  - `tests.unit.test_externals::test_externals_graph_set_status_enforces_transition_rules`
  - `tests.unit.test_externals::test_externals_graph_set_status_rejects_invalid_status`
  - `tests.unit.test_externals::test_externals_identity`
  - `tests.unit.test_externals::test_externals_kv_ops`
  - `tests.unit.test_externals::test_externals_search_content_caps_results`
  - `tests.unit.test_externals::test_externals_send_message_rate_limit`
  - `tests.unit.test_externals::test_externals_workspace_ops`
  - `tests.unit.test_externals::test_propose_changes_excludes_bundle_paths`
  - `tests.unit.test_externals::test_request_human_input_blocks_until_response`
  - `tests.unit.test_externals::test_request_human_input_times_out_and_resets_status`
  - `tests.unit.test_externals::test_semantic_search_and_find_similar_delegate`
  - `tests.unit.test_externals::test_semantic_search_returns_empty_when_service_unavailable`
  - `tests.unit.test_externals::test_semantic_search_returns_empty_without_service`
  - `tests.unit.test_graph::test_nodestore_add_edge`
  - `tests.unit.test_graph::test_nodestore_batch_commits_once_for_grouped_writes`
  - `tests.unit.test_graph::test_nodestore_delete`
  - `tests.unit.test_graph::test_nodestore_edge_directions`
  - `tests.unit.test_graph::test_nodestore_edge_uniqueness`
  - `tests.unit.test_graph::test_nodestore_get_children`
  - `tests.unit.test_graph::test_nodestore_list_with_filters`
  - `tests.unit.test_graph::test_nodestore_set_status`
  - `tests.unit.test_graph::test_nodestore_transition_status_awaiting_input`
  - `tests.unit.test_graph::test_nodestore_transition_status_awaiting_review`
  - `tests.unit.test_graph::test_nodestore_transition_status_competing_updates_only_one_wins`
  - `tests.unit.test_graph::test_nodestore_transition_status_invalid`
  - `tests.unit.test_graph::test_nodestore_transition_status_valid`
  - `tests.unit.test_graph::test_nodestore_upsert_and_get`
  - `tests.unit.test_graph::test_shared_db_coexistence`
  - `tests.unit.test_lsp_server::test_lsp_chat_command_requests_external_document`
  - `tests.unit.test_lsp_server::test_lsp_code_action_returns_chat_and_trigger`
  - `tests.unit.test_lsp_server::test_lsp_did_change_writes_file_and_emits_event`
  - `tests.unit.test_lsp_server::test_lsp_did_save_emits_event`
  - `tests.unit.test_lsp_server::test_lsp_open_change_save_lifecycle`
  - `tests.unit.test_lsp_server::test_lsp_server_accepts_db_path`
  - `tests.unit.test_lsp_server::test_lsp_server_accepts_shared_services`
  - `tests.unit.test_lsp_server::test_lsp_server_creates`
  - `tests.unit.test_lsp_server::test_lsp_trigger_command_emits_agent_message_event`
  - `tests.unit.test_projections::test_project_bundle_overlays`
  - `tests.unit.test_projections::test_project_bundle_rules_override_overlays`
  - `tests.unit.test_projections::test_project_changed_node`
  - `tests.unit.test_projections::test_project_new_node`
  - `tests.unit.test_projections::test_project_unchanged_node`
  - `tests.unit.test_projections::test_project_unchanged_node_can_sync_existing_bundle_tools`
  - `tests.unit.test_reconciler::test_directory_bundles_refreshed_on_startup`
  - `tests.unit.test_reconciler::test_directory_nodes_materialize_parent_chain`
  - `tests.unit.test_reconciler::test_directory_nodes_removed_when_tree_disappears`
  - `tests.unit.test_reconciler::test_directory_subscriptions_refreshed_on_startup`
  - `tests.unit.test_reconciler::test_file_lock_cache_evicts_unused_entries`
  - `tests.unit.test_reconciler::test_full_scan_discovers_registers_and_emits`
  - `tests.unit.test_reconciler::test_no_self_reflect_subscription_when_disabled`
  - `tests.unit.test_reconciler::test_provision_bundle_clears_self_reflect_when_disabled`
  - `tests.unit.test_reconciler::test_provision_bundle_persists_self_reflect_config`
  - `tests.unit.test_reconciler::test_reconcile_cycle_handles_new_and_deleted_files`
  - `tests.unit.test_reconciler::test_reconcile_cycle_modified_file_only`
  - `tests.unit.test_reconciler::test_reconcile_subscription_idempotency`
  - `tests.unit.test_reconciler::test_reconciler_content_changed_event_triggers_reconcile`
  - `tests.unit.test_reconciler::test_reconciler_deindexes_files_on_delete`
  - `tests.unit.test_reconciler::test_reconciler_handles_malformed_source`
  - `tests.unit.test_reconciler::test_reconciler_indexes_files_when_search_service_available`
  - `tests.unit.test_reconciler::test_reconciler_search_index_failures_do_not_break_reconcile`
  - `tests.unit.test_reconciler::test_reconciler_survives_cycle_error`
  - `tests.unit.test_reconciler::test_reconciler_watch_import_error_is_not_suppressed`
  - `tests.unit.test_reconciler::test_self_reflect_subscription_registered`
  - `tests.unit.test_reconciler::test_virtual_agents_bootstrapped_with_subscriptions`
  - `tests.unit.test_runner::test_runner_build_prompt_for_virtual_node`
  - `tests.unit.test_runner::test_runner_build_prompt_via_actor`
  - `tests.unit.test_runner::test_runner_creates_actor_on_route`
  - `tests.unit.test_runner::test_runner_does_not_evict_busy_actors`
  - `tests.unit.test_runner::test_runner_evicts_idle_actors`
  - `tests.unit.test_runner::test_runner_handles_concurrent_triggers_across_agents`
  - `tests.unit.test_runner::test_runner_passes_search_service_to_actor`
  - `tests.unit.test_runner::test_runner_reuses_existing_actor`
  - `tests.unit.test_runner::test_runner_routes_dispatch_to_actor_inbox`
  - `tests.unit.test_runner::test_runner_stop_and_wait`
  - `tests.unit.test_services::test_runtime_services_search_disabled`
  - `tests.unit.test_services::test_runtime_services_search_enabled`
  - `tests.unit.test_subscription_registry::test_registry_cache_invalidation`
  - `tests.unit.test_subscription_registry::test_registry_not_from_agents_filter`
  - `tests.unit.test_subscription_registry::test_registry_register_and_match`
  - `tests.unit.test_subscription_registry::test_registry_register_updates_cache_incrementally`
  - `tests.unit.test_subscription_registry::test_registry_unregister`
  - `tests.unit.test_subscription_registry::test_registry_unregister_updates_cache_incrementally`

### WORKSPACE_OPEN_FAILED_FROM_FD_PRESSURE
- Affected tests: `1`
- Explanation: Cairn workspace open failed during perf test (downstream of FD pressure).
- Proposed fixes:
  - Re-run perf test after FD fix; likely not a logical workspace bug.
  - If persistent, add retry/backoff or tighter workspace close semantics in perf fixture teardown.
- Affected test IDs:
  - `tests.integration.test_performance::test_perf_reconciler_load_1000_files_10_nodes_each`

### LSP_ACCEPTANCE_TIMEOUT_UNDER_RESOURCE_PRESSURE
- Affected tests: `1`
- Explanation: Acceptance LSP init timed out (likely resource pressure side effect).
- Proposed fixes:
  - Re-run acceptance with clean FD state first; likely secondary failure.
  - If still flaky, increase handshake timeout or improve startup readiness checks before first LSP read.
- Affected test IDs:
  - `tests.acceptance.test_live_runtime_real_llm::test_acceptance_process_lsp_open_save_emits_content_changed_event`

### STALE_COMPANION_TEST_EXPECTATION
- Affected tests: `1`
- Explanation: Legacy assertion conflicts with new companion bundle introduction.
- Proposed fixes:
  - Update `tests/unit/test_reflection_tools.py::test_companion_bundle_removed` to align with current architecture.
  - Replace with positive assertions that `bundles/companion` exists and has expected bundle/tool files.
- Affected test IDs:
  - `tests.unit.test_reflection_tools::test_companion_bundle_removed`

## Underlying Issue Graph
1. `Too many open files` appears in Grail/logging/startup paths.
2. Once FD limit is reached, sqlite and workspace open calls start failing (`unable to open database file`, `WORKSPACE_OPEN_FAILED`).
3. Broad fixture setup failures then fan out across actor/graph/reconciler/runner/subscription tests.
4. One independent failure remains: stale companion-removal assertion.

## Work Overview for Next Steps 2 and 3
### Step 2: Add Integration Tests that Execute Companion Tools Against KV
- Goal: Validate companion tool scripts in runtime execution, not only existence/content checks.
- Test file target: `tests/integration/test_grail_runtime_tools.py` (extend) or new `tests/integration/test_companion_runtime_tools.py`.
- Work items:
  - Build workspace stub with companion tool sources (`companion_summarize`, `companion_reflect`, `companion_link`, `aggregate_digest`).
  - Provide concrete capability funcs: `kv_get`, `kv_set`, `my_correlation_id` backed by in-memory dict state.
  - Execute each tool via Grail runtime (`discover_tools` + `tool.execute`) and assert KV mutations and outputs.
  - Add negative/edge tests (empty tags, duplicate links, optional insight).
- Acceptance criteria:
  - Tools parse and execute successfully.
  - KV state reflects expected append/trim semantics and field names.
  - No mocks of tool internals; runtime path is exercised end-to-end at tool layer.

### Step 3: Add End-to-End Companion Flow Test (Primary -> Reflection -> Digest -> Observer)
- Goal: Validate the real multi-layer behavior chain, not isolated units.
- Test file target: new `tests/integration/test_companion_e2e_flow.py`.
- Work items:
  - Bring up in-process services (`EventStore`, `NodeStore`, `ActorPool`, `CairnWorkspaceService`, reconciler).
  - Create at least one code agent with `self_reflect` enabled and one companion observer virtual agent.
  - Seed deterministic kernel behavior (fake kernel responses) to avoid external LLM dependency while still using real actor/event wiring.
  - Trigger a primary turn, assert reflection turn classification and companion KV updates.
  - Emit/assert `TurnDigestedEvent` path and observer aggregation (`project/activity_log`, `project/tag_frequency`).
  - Verify no self-loop processing using `not_from_agents` policy where applicable.
- Acceptance criteria:
  - Event chain completes with expected ordering and payload shape.
  - Observer writes project-level aggregate KV data.
  - Test proves “real world usage” for companion architecture without relying on live external model APIs.

## Recommended Execution Order
1. Fix FD/resource leak and stale companion-removal test.
2. Re-run full suite and confirm baseline stability.
3. Implement Step 2 integration tests (tool runtime).
4. Implement Step 3 end-to-end companion flow test.
5. Re-run full suite and any live acceptance tests where environment permits.

