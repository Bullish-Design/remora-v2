# Context — 63-web-ui-improvement-template

Current focus:
- Execute the v7 corrective implementation plan end-to-end with per-step commits.

Current status:
- v6 implementation complete and released.
- v7 Step 1 complete: Sigma settings upgrade (edge labels/events, hide-on-move, pan boundaries, native node hover draw hook).
- v7 Step 2 complete: edge enter/leave/click handlers with sidebar relationship details and visual focus.
- v7 Step 3 complete: peripheral dock now uses grid-cell placement with min width + enforced gaps.
- v7 Step 4 complete: core-zone minimum vertical reservation and core-bounded custom camera fit.
- v7 Step 5 complete: explicit zone separator rule + "supporting nodes" label in canvas render pass.
- Unit checks passing after Step 5.

Constraints and direction:
- Node labels remain always visible.
- Scope remains graph-view focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Implement v7 Step 6 (hierarchy box alpha/tint overhaul), then continue sequentially through Step 10.
