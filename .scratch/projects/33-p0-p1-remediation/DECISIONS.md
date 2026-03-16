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
