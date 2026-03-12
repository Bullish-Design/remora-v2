# Context

## Status
Setup complete. Comprehensive configuration review written. Awaiting user direction.

## What Was Done
1. Created project directory: `.scratch/projects/06-config-review/`
2. Wrote comprehensive `CONFIG_REVIEW.md` with:
   - Full inventory of all config sources
   - Analysis of configuration flow and duplication
   - Issues and anti-patterns identified
   - 10 recommendations for improvement
   - Proposed unified schema
   - Migration path

## Key Findings

### Configuration Sources (4 mechanisms)
1. `remora.yaml` → `Config` class (17 fields)
2. `bundle.yaml` → Per-bundle agent config
3. Environment variables → `REMORA_*` prefix + `${VAR:-default}` expansion
4. CLI arguments → Typer flags (port, no-web, run-seconds)

### Primary Issues
1. **Duplicate defaults** — Model default appears in 3 places
2. **Unused field** — `project_path` never used
3. **Fragmented config** — Bundle behavior in separate filesystem location
4. **No per-node-type config** — Can't configure different behavior for functions vs classes
5. **Hardcoded values** — Web server, fallback prompts, etc.

### Key Recommendations
1. Consolidate bundle.yaml into remora.yaml
2. Add per-node-type configuration overrides
3. Move web server config into Config class
4. Create single source of truth for defaults
5. Remove dead code (project_path, fallback prompt)

## Files Created
- `.scratch/projects/06-config-review/CONFIG_REVIEW.md`
- `.scratch/projects/06-config-review/PLAN.md`
- `.scratch/projects/06-config-review/CONTEXT.md` (this file)
