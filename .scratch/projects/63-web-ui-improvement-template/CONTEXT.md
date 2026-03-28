# Context — 63-web-ui-improvement-template

Current focus:
- Analyze post-v5 screenshot quality and define v6 corrective plan.

Current status:
- Latest screenshot reviewed:
  - `.scratch/projects/63-web-ui-improvement-template/ui-playwright-20260328-121351-721.png`
- Remaining issues identified despite v5:
  - labels regress to verbose absolute paths,
  - composition still fragmented into disconnected islands,
  - weak primary-vs-peripheral visual hierarchy,
  - filesystem grouping too subtle for fast comprehension.
- New v6 corrective guide created:
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT_V6.md`
  - Introduces core/peripheral zoning, concise relative labels, stronger hierarchy cues, and refined acceptance targets.

Constraints and direction:
- Node labels remain always visible.
- Scope remains graph-view focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Implement `CONCEPT_V6.md` end-to-end with commit/push after each step, then run full web subset verification and release handoff.
