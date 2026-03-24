## NO SUBAGENTS

# PLAN — 49-demo-v2-update (WS1 Execution)

## Goal
Complete **WS1: Harden Virtual Bundle Runtime Reliability** from `DEMO_UPDATE_IMPLEMENTATION_GUIDE.md` with implementation and verification, including real-world usage tests.

## Steps
1. Add failing WS1 tests for real-world tool execution and loop-guard behavior.
2. Patch `review-agent` tools:
   - `review_diff.pym` (`graph_get_node` optional return + defensive source handling + bounded output)
   - `list_recent_changes.pym` (bounded output length)
   - `submit_review.pym` (input validation + unexpected `send_message` shape handling)
3. Patch `companion` tool:
   - `aggregate_digest.pym` (type guards for malformed KV values + bounded `summary`/`insight`)
4. Harden virtual bundle prompts:
   - `review-agent/bundle.yaml`
   - `companion/bundle.yaml` (single-shot behavior and stricter failure handling)
5. Add runtime loop guard for reactive event storms:
   - Enforce max reactive turns per `correlation_id` per agent (default 3)
   - Add/adjust runtime config and tests.
6. Run targeted tests, then related suites; resolve regressions.
7. Update project tracking docs (`PROGRESS.md`, `CONTEXT.md`, `DECISIONS.md`).

## Acceptance Criteria
- `review-agent` and `companion` tool scripts handle `None`/malformed inputs without raising type/runtime errors.
- Prompt contracts include explicit stop-on-failure behavior.
- Runtime bounds repeated triggers per `correlation_id` per agent.
- New real-world example tests pass and validate WS1 behavior.

## NO SUBAGENTS
