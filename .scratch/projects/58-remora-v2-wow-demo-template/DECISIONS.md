# Decisions — 58-remora-v2-wow-demo-template

## 2026-03-27 — Use `58-` numbering with kebab-case project name
- Decision: create `.scratch/projects/58-remora-v2-wow-demo-template`.
- Rationale: follows existing monotonic project numbering and repository naming conventions.

## 2026-03-27 — Prioritize architecture-visible demo concepts
- Decision: bias ideas toward event flows, graph/proposal visibility, and autonomous orchestration.
- Rationale: technical audiences are most impressed by transparent system behavior under change, not static UI polish.

## 2026-03-27 — Recommend one top demo for first implementation
- Decision: rank "Event Storm Control Room" as first build candidate.
- Rationale: best balance of visual impact, architectural depth, and feasibility.

## 2026-03-27 — Include a backup runbook independent of model success
- Decision: author a fallback demo centered on deterministic graph projection + event replay with no required chat/model interaction.
- Rationale: protects live presentation quality when upstream model latency/availability is unstable.

## 2026-03-27 — Keep both runbooks API-first and UI-assisted
- Decision: every key claim in runbooks is backed by explicit API queries (`/api/health`, `/api/nodes`, `/api/edges`, `/api/events`, `/sse`), with web UI as amplification layer.
- Rationale: technical audiences trust inspectable evidence over purely visual demos.

## 2026-03-27 — Package setup flows as executable Python scripts
- Decision: replace long manual setup blocks with executable setup scripts (`setup_primary_event_storm_demo.py`, `setup_backup_graph_boot_demo.py`).
- Rationale: faster pre-demo setup, fewer copy/paste errors, and easier repeatable dry-runs.

## 2026-03-27 — Expand Idea #6 into a full technical brief
- Decision: author a dedicated detailed overview for "Instant Local Knowledge Graph Boot".
- Rationale: user indicated Idea #6 is a strong demo candidate and needs a deeper execution narrative.

## 2026-03-27 — Standardize Idea #6 on `pallets/click`
- Decision: revise the Idea #6 document around a clone-first flow using `pallets/click` as the target repo.
- Rationale: Click provides a strong balance of real-world credibility, manageable complexity, and fast graph boot timing for live demos.

## 2026-03-27 — Treat cross-file relationship completeness as P0 for hotspot-centric Idea #6
- Decision: mark reconciler relationship completeness (forward references unresolved on first scan) as a required fix when the demo narrative depends on connectivity hotspots.
- Rationale: without reliable `imports`/`inherits` edges, hotspot outputs are structurally biased and less credible to a technical audience.

## 2026-03-27 — Prefer narrative correction over lifecycle reorder for immediate delivery
- Decision: for near-term demo readiness, adjust Idea #6 narrative to \"instant loaded graph\" rather than \"watch it fill\".
- Rationale: current lifecycle performs full scan before web startup; changing startup ordering is a higher-risk runtime behavior change.
