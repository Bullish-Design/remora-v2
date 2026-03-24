# PLAN 04 - Wider X Distribution In Tall Layout

## Absolute Rule
- NO SUBAGENTS: all work for this project is done directly in this session.

## Objective
- Keep the tall/sidebar-friendly layout but widen horizontal distribution so nodes do not collapse into a single vertical spine.

## Steps
1. Add failing test markers for new x-distribution controls.
2. Introduce explicit x-distribution constants.
3. Expand node-type tracks to include directory/file and increase separation.
4. Add deterministic depth-wave/hash offset to spread long single-child chains.
5. Validate with targeted tests.

## Acceptance Criteria
- Nodes remain organized top-to-bottom by file/depth.
- X distribution is visibly broader and no longer a near-single column.
- Tests pass.

## Absolute Rule (Reaffirmed)
- NO SUBAGENTS: all exploration, edits, and validation are performed directly.
