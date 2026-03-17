# Here is the full analysis of all four files.

---
## 1. src/remora/core/transaction.py

Exists: YES (62 lines)

Key sections

- Lines 1-13: Module docstring + imports. Imports EventBus, TriggerDispatcher, and Event from the
events subpackage.
- Lines 15-59: TransactionContext class.
  - __init__ (lines 18-28): Takes db, event_bus, dispatcher. Initializes _depth = 0 and
_deferred_events: list[Event] = [].
  - batch() context manager (lines 30-51): The core logic. Increment depth on enter. On
BaseException, only rollback the DB if at the outermost level (_depth == 1, checked before
decrement). finally decrements depth and, at depth 0, commits and fans out deferred events in order
(bus first, then dispatcher). Clears deferred list unconditionally in finally.
  - in_batch property (lines 53-55): Returns True when _depth > 0.
  - defer_event() (lines 57-59): Appends an event to the deferred list.
- Line 62: __all__ = ["TransactionContext"]

Issues noticed

- Potential double-clear on failure: In batch(), when failed = True and _depth == 1 (the except
block), _deferred_events.clear() is called. The finally block then also calls
_deferred_events.clear() unconditionally. This is harmless (clearing an empty list), but redundant.
- No rollback for inner failures: If _depth > 1 when an exception is raised, the rollback is
skipped (the outer batch is responsible), but _deferred_events are also not cleared at that point —
the outer batch() will clear them in its own except branch. This is correct behavior but subtly
relies on the outer frame catching the exception.
- Events fanned out outside the try block: The await self._event_bus.emit(event) / await
self._dispatcher.dispatch(event) calls inside finally at depth 0 are executed after commit. If they
raise, the commit has already happened but the exception will propagate. No error handling around
fan-out. This is a reasonable trade-off but worth flagging.
- No __all__ omissions: The single public class is exported correctly.

---
## 2. src/remora/core/services.py

Exists: YES (103 lines)

Key sections

- Lines 1-19: Imports, including from remora.core.transaction import TransactionContext.
- Lines 22-52: RuntimeServices.__init__. Construction order matters:
  a. db stored (line 28)
  b. EventBus, SubscriptionRegistry, TriggerDispatcher (lines 31-33)
  c. TransactionContext(db, event_bus, dispatcher) assigned to self.tx (line 34)
  d. NodeStore(db, tx=self.tx) (line 35)
  e. EventStore(db=..., event_bus=..., dispatcher=..., metrics=..., tx=self.tx) (lines 36-42)
  f. FileReconciler also receives tx=self.tx (line 71)
- Lines 54-83: initialize() - creates tables, initializes workspace, optionally wires
SearchService, creates FileReconciler and starts it, creates ActorPool.
- Lines 85-100: close() - orderly teardown of reconciler, runner, search service, workspace, and
DB.
- Line 103: __all__ = ["RuntimeServices"]

Issues noticed

- tx is wired into NodeStore, EventStore, and FileReconciler, but not into ActorPool (lines 75-83).
If ActorPool or its actors need transactional writes, they would bypass TransactionContext. This
is likely intentional (actors may manage their own tx scopes), but worth verifying.
- SubscriptionRegistry is passed db directly (line 32) without tx. If subscriptions are written
alongside other DB operations in a batch, they won't participate in the shared transaction.
- No aiosqlite.Connection isolation: The same db connection is passed to all stores. This is
correct for a shared transaction model, but means all stores implicitly share autocommit state —
they must all use tx.batch() or none should call db.commit() directly.

---
## 3. src/remora/core/externals.py

Exists: YES (529 lines)

Key sections: request_human_input and EXTERNALS_VERSION

- Line 30: EXTERNALS_VERSION = 1 — module-level constant.
- Lines 302-327: CommunicationCapabilities.request_human_input:
  - Generates a request_id UUID (line 307).
  - Calls self._event_store.create_response_future(request_id) (line 308) to register a future.
  - Transitions node status to AWAITING_INPUT (line 310).
  - Emits a HumanInputRequestEvent (lines 311-319).
  - Awaits the future with a timeout of self._human_input_timeout_s (line 322).
  - On success, transitions status back to RUNNING (line 323) and returns the result string.
  - On TimeoutError (line 325), calls self._event_store.discard_response_future(request_id) and
re-raises — node status is not reset to RUNNING on timeout.
- Line 519-529: __all__ exports EXTERNALS_VERSION plus all capability classes and TurnContext.

Issues noticed

- Status leak on timeout: In request_human_input, if asyncio.wait_for times out, the node is left
in NodeStatus.AWAITING_INPUT permanently. The except TimeoutError block discards the future but
does not call transition_status(self._node_id, NodeStatus.RUNNING) (or any other status). This is a
clear bug — the node will be stuck in AWAITING_INPUT after timeout.
- EXTERNALS_VERSION = 1 vs BehaviorConfig.externals_version: The constant on line 30 is hardcoded
to 1. BehaviorConfig (in config.py line 164) has externals_version: int = 1 and the BundleConfig
(line 211) has externals_version: int | None = None. These are consistent at version 1 for now, but
the constant in externals.py is the ground-truth authoritative value — the config fields are for
validation/routing. The relationship between them is not enforced anywhere in this file.
- _collect_changed_files skips _bundle/ paths (line 351): This is a heuristic filter. If an agent
writes files outside _bundle/ unintentionally, they will all appear as changed. No other filtering
(e.g., diff against original workspace state) is applied.
- No __all__ omissions: _resolve_broadcast_targets is private (underscore-prefixed) and correctly
omitted. All public classes and EXTERNALS_VERSION are present.

---
## 4. src/remora/core/config.py

Exists: YES (456 lines)

Key sections

- Lines 104-126: ProjectConfig — project_path, discovery_paths, discovery_languages,
workspace_ignore_patterns. Validator on discovery_paths prevents empty tuples and blank strings.
- Lines 129-140: RuntimeConfig — 9 execution-engine fields including human_input_timeout_s, rate
limits, concurrency.
- Lines 143-150: InfraConfig — model URL/key, timeout, workspace_root.
- Lines 152-184: BehaviorConfig — model_default, max_turns, search paths, bundle_overlays,
bundle_rules, languages, language_map, prompt_templates, externals_version. Validators on
language_map and search paths.
- Lines 229-264: Config(BaseSettings) — composes all sub-models. Uses env_prefix="REMORA_",
frozen=True. Has resolve_bundle() method.
- Lines 305-370: _nest_flat_config — maps flat dict keys to nested sub-model keys. The four key
sets (project_keys, runtime_keys, infra_keys, behavior_keys) must stay in sync with the sub-model
fields.
- Lines 441-456: __all__

Issues noticed

- Missing exports in __all__: The following public symbols are defined in the module but absent
from __all__ (lines 441-456):
  - ProjectConfig (line 104)
  - RuntimeConfig (line 129)
  - InfraConfig (line 143)
  - BehaviorConfig (line 152)
  - _nest_flat_config is private so correctly omitted, but the four sub-models are part of the
public API and not exported.
  - resolve_query_search_paths (line 412) is present in __all__ (line 455) — that's fine.
  - resolve_bundle_dirs is present (line 454) — fine.
  - load_config is present (line 453) — fine.
  - What is missing: ProjectConfig, RuntimeConfig, InfraConfig, BehaviorConfig.
- _nest_flat_config key drift risk: The four frozen key sets inside the function (lines 309-338)
must be manually kept in sync with the sub-model field names. If a field is added to (say)
RuntimeConfig but not added to runtime_keys, flat config files will silently ignore that key (it
falls into nested[key] = value on line 359, which passes it to Config(**nested) as a top-level key,
likely causing a pydantic validation error rather than silent failure — but still not a great DX).
- BundleConfig.max_turns validator (lines 213-216): Returns max(1, value), so setting max_turns: 0
in a bundle silently becomes 1. The comment in the class definition (max_turns: int = 0) has 0 as
default, but after validation it would become 1. The intent (0 = inherit from global) is not
achievable through the validator — this appears to be a latent bug or design inconsistency with the
"inherit" semantic implied by the default of 0.