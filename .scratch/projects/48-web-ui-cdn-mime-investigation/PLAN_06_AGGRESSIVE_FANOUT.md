# PLAN 06 - Aggressive Fanout For Long Chains

## Absolute Rule
- NO SUBAGENTS: all work for this project is done directly in this session.

## Objective
- Break persistent single-spine rendering by increasing deterministic x fanout and reducing y dominance.

## Steps
1. Add failing test marker for zigzag fanout control.
2. Reduce depth row spacing further.
3. Increase base x spread constants.
4. Add depth-zigzag x term that grows with depth.
5. Validate with targeted tests.

## Acceptance Criteria
- Chain nodes spread horizontally in a noticeable zigzag/fanout pattern.
- Vertical hierarchy remains readable.
- Tests pass.

## Absolute Rule (Reaffirmed)
- NO SUBAGENTS: all exploration, edits, and validation are performed directly.
