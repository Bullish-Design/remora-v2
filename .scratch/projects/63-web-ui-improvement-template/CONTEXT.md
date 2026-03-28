# Context — 63-web-ui-improvement-template

Current focus:
- Evaluate post-v4 screenshot quality and define v5 remediation plan.

Current status:
- Latest screenshot reviewed:
  - `.scratch/projects/63-web-ui-improvement-template/ui-playwright-20260328-110404-178.png`
- Main remaining problems identified:
  - Under-utilized canvas and fragmented component placement.
  - Long-distance dependency arcs from topology-unaware placement.
  - Remaining duplicate-label ambiguity.
  - Filesystem hierarchy not consistently useful as an organizing aid.
- New v5 design + implementation guide created:
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT_V5.md`

Constraints and direction:
- Node labels remain always visible.
- Scope remains graph-view focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Implement `CONCEPT_V5.md`:
  - component-first layout,
  - occupancy/readability-constrained fit,
  - stronger global label disambiguation,
  - filesystem fallback grouping,
  - acceptance metrics for occupancy/overlap/component coherence.
