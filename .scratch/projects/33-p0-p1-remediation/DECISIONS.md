# Decisions

## 2026-03-15 - Path traversal handling in proposal endpoints
- Decision: Reject any resolved proposal target path outside `workspace_service._project_root` with HTTP 400.
- Rationale: Prevent arbitrary file read/write from crafted workspace proposal paths while returning explicit client-visible rejection instead of 500.

## 2026-03-15 - CSRF scope and allowlist
- Decision: Apply Origin validation middleware to POST/PUT/DELETE and allow only localhost/127.0.0.1 browser origins.
- Rationale: Keep local-web UX working while blocking cross-site browser writes from external origins.

## 2026-03-15 - Actor depth-state memory hygiene
- Decision: Add timestamped depth entries with a 5-minute TTL and periodic cleanup every 100 trigger checks.
- Rationale: Bound long-lived correlation-id memory growth without introducing background tasks.

## 2026-03-15 - Reconciler file-lock lifecycle
- Decision: Track file locks per reconcile generation and evict unlocked locks unused by the latest generation.
- Rationale: Prevent unbounded lock-map growth while preserving per-file mutual exclusion during active reconciliation.

## 2026-03-15 - EventBus dispatch semantics
- Decision: Replace MRO-based dispatch with exact event-type dispatch plus explicit `Event` base dispatch.
- Rationale: Avoid accidental delivery to intermediate base-class subscribers while preserving global/base handler behavior.

## 2026-03-15 - Node status transition atomicity
- Decision: Implement `transition_status` as a single conditional SQL update with allowed source statuses in the `WHERE` clause.
- Rationale: Prevent stale read/validate/write races where invalid transitions can be committed under concurrent status changes.

## 2026-03-15 - External status writes must respect transition rules
- Decision: Route `graph_set_status` through `transition_status` and enum-validate `new_status`.
- Rationale: Prevent tools from bypassing node lifecycle constraints via direct status mutation.

## 2026-03-15 - Batched graph writes
- Decision: Add `NodeStore.batch()` with deferred commit behavior and apply it around reconciler mutation bursts.
- Rationale: Reduce commit frequency during reconciliation while keeping single-operation call sites unchanged.
