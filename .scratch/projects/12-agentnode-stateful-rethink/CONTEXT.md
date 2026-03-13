# Context

## Current Status
REFACTORING_GUIDE.md has been written with 12 incremental PRs and 3 investigation items.

## Key Decisions
1. **Scope**: User annotated each appendix idea with Implement/Investigate/Do Not Implement.
2. **Format**: Incremental PRs, each self-contained and independently committable.
3. **LSP**: Keep it (user explicitly chose to keep).
4. **Bundles**: Implement A4 alternative (additive, not flatten). Implement A5 (drop companion).
5. **Events**: Implement A6 middle ground (typed classes, generic envelope storage).

## User's Appendix Annotations
- A1 (merge stores): **Investigate** — concern about future non-CST node types
- A2 (no stable fallback): **Implement**
- A3 (bundle.yaml as workspace file): **Implement**
- A4 (unify tools): **Implement alternative** (additive system)
- A5 (drop companion): **Implement**
- A6 (event envelope): **Implement middle ground**
- A7 (simplify subscriptions): **Do Not Implement**
- A8 (rename everything): **Implement**
- A9 (event sourcing): **Do Not Implement**
- A10 (kill _preview_text): **Implement**
- A11 (config as workspace): **Do Not Implement**
- A12 (drop LSP): **Do Not Implement**
- A13 (user replies via send_message): **Implement**
- A14 (separate identity/content/runtime): **Investigate Further**
- A15 (directories not agents): **Do Not Implement**
- A16 (KV store): **Implement**
- A17 (fsdantic overlays): **Investigate Further**

## Next Step
User reviews REFACTORING_GUIDE.md. Then begin implementation with PR1.
