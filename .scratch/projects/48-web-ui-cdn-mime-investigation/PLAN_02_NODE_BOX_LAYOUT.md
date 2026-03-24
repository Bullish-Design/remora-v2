# PLAN 02 - Node Boxes And Organized Layout

## Absolute Rule
- NO SUBAGENTS: all work for this project is done directly in this session.

## Objective
- Update the web graph UI so nodes present as labeled boxes and positions are organized deterministically for readability.

## Steps
1. Add/extend unit tests for static HTML expectations (box-label renderer hook + organization constants).
2. Implement a custom Sigma node label drawer that renders rounded rectangular boxes containing node names.
3. Replace random file-cluster placement with deterministic organization:
- file lanes (columns)
- parent-depth rows
- deterministic sibling spread to avoid overlaps
4. Remove stale ForceAtlas2-related dead config and keep renderer settings aligned with new behavior.
5. Run targeted tests and verify pass.

## Acceptance Criteria
- Node names are rendered as box-style labels in the graph renderer configuration.
- Node positions are deterministic and visibly organized by file/depth/sibling structure.
- No references remain to broken or unused ForceAtlas2 layout controls.
- Targeted tests pass.

## Absolute Rule (Reaffirmed)
- NO SUBAGENTS: all exploration, edits, and validation are performed directly.
