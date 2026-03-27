# PLAN

## Goal
Create one Allium distillation per core Remora v2 subsystem.

## Output
- 12 subsystem-specific `.allium` files under `specs/subsystems/`
- `specs/subsystems/README.md` index with scope map

## Steps
1. Define stable subsystem file naming and boundaries.
2. Draft each distillation with explicit scope include/exclude comments.
3. Cross-check for terminology consistency and avoid implementation leakage.
4. Produce index mapping subsystem -> spec file.

## Acceptance
- One `.allium` file exists for each subsystem listed by the user.
- All files start with `-- allium: 3`.
- README index points to all files.
