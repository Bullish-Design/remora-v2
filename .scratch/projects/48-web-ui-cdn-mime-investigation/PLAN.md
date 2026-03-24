# PLAN

## Absolute Rule
- NO SUBAGENTS: all work for this project is done directly in this session.

## Objective
- Diagnose the web UI console errors on `localhost:8080` related to blocked CDN scripts and explain the underlying causes with evidence.

## Steps
1. Create numbered project directory and standard tracking files.
2. Locate the web UI script references and runtime call-sites in source.
3. Verify what the referenced CDN URLs return (status, headers, MIME type, body shape).
4. Map each console error to direct and cascading root causes.
5. Document findings and recommended remediation options.

## Acceptance Criteria
- Each reported console error is explained with a concrete root cause.
- Evidence includes exact source file references and CDN response behavior.
- Explanation distinguishes primary failures from downstream runtime fallout.

## Absolute Rule (Reaffirmed)
- NO SUBAGENTS: all exploration, analysis, and documentation is performed directly.
