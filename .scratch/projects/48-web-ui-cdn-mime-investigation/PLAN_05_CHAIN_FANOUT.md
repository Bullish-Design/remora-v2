# PLAN 05 - Chain Fanout Rebalance

## Absolute Rule
- NO SUBAGENTS: all work for this project is done directly in this session.

## Objective
- Prevent long parent-child chains from collapsing into a single near-center column by adding deterministic depth-based horizontal fanout.

## Steps
1. Add failing test marker for new fanout control constants.
2. Reduce depth row spacing to shrink y-range pressure.
3. Add depth-based x fanout component for single-child chains and general nodes.
4. Increase x-wave amplitude scaling with depth.
5. Validate with targeted tests.

## Acceptance Criteria
- Long chains occupy materially more horizontal width.
- Vertical organization remains intact.
- Tests pass.

## Absolute Rule (Reaffirmed)
- NO SUBAGENTS: all exploration, edits, and validation are performed directly.
