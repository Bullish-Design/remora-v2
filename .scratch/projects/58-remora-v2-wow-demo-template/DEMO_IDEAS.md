# Remora v2 Demo Ideas (Technical + Wow Factor)

## Scoring Lens
- Wow: audience-visible surprise/impact in a live session.
- Technical Depth: demonstrates real remora-v2 architecture, not surface scripting.
- Feasibility: can be prepared and run reliably in a demo window.

## Idea 1: Event Storm Control Room (Top Pick)
- Hook: trigger a burst of repository events and show remora-v2 coordinating multiple agents in real time.
- What audience sees:
  - live event feed
  - node/proposal updates
  - autonomous stabilization actions
- Capabilities showcased:
  - EventStore as source of truth
  - reactive dispatch/subscriptions
  - proposal generation and acceptance pipeline
- Wow moment: system absorbs an event storm and converges without manual triage.
- Complexity: medium-high.
- Risk: requires deterministic event playback and clear visual instrumentation.

## Idea 2: Time-Travel Debugging for Agent Decisions
- Hook: replay one difficult decision path from raw events to final accepted action.
- What audience sees:
  - scrub through event timeline
  - inspect branch points ("why this proposal won")
  - compare before/after graph state
- Capabilities showcased:
  - event sourcing and replay semantics
  - projection consistency
  - explainable agent decisions
- Wow moment: instant, inspectable forensics for autonomous behavior.
- Complexity: medium.
- Risk: needs polished timeline UI/query workflow.

## Idea 3: Self-Healing Refactor Arena
- Hook: intentionally introduce breaking edits; remora-v2 detects impact and coordinates fix proposals.
- What audience sees:
  - breaking change injected live
  - affected nodes light up in dependency graph
  - generated proposals/tests restore green state
- Capabilities showcased:
  - graph-aware change impact analysis
  - autonomous proposal loops
  - test-aware remediation workflow
- Wow moment: visible "break it -> system heals it" loop on stage.
- Complexity: high.
- Risk: higher setup burden; can fail noisily without curated fixture repo.

## Idea 4: Multi-Agent Architecture Design Review
- Hook: feed an architectural diff and have specialized virtual bundles conduct parallel review perspectives.
- What audience sees:
  - reviewer lanes (correctness, performance, operability, API stability)
  - converged summary with prioritized actions
- Capabilities showcased:
  - virtual bundle specialization
  - shared event context
  - synthesis over multiple agent outputs
- Wow moment: parallel expert review in one coherent decision packet.
- Complexity: medium.
- Risk: requires disciplined prompt/contracts to avoid generic commentary.

## Idea 5: Spec-to-Execution Trace Bridge
- Hook: define intended behavior, then show the runtime trace proving execution matched spec constraints.
- What audience sees:
  - declared intent/spec artifact
  - generated checks/tests
  - live trace mapped back to obligations
- Capabilities showcased:
  - traceability from intent -> events -> outcome
  - structured compliance checks
- Wow moment: closes "LLM said it" vs "system proved it" trust gap.
- Complexity: medium-high.
- Risk: mapping layer between spec language and runtime events needs careful design.

## Idea 6: Instant Local Knowledge Graph Boot
- Hook: start from cold workspace and build useful graph context fast enough to narrate live.
- What audience sees:
  - node graph materialization
  - hot spots and change clusters
  - immediate navigable intelligence for review/refactor
- Capabilities showcased:
  - discovery/reconciliation flow
  - node projection and graph storage
  - developer-facing observability
- Wow moment: "from zero context to actionable map" in minutes.
- Complexity: medium.
- Risk: performance depends on workspace size and fixture selection.

## Ranked Shortlist
1. Event Storm Control Room
2. Time-Travel Debugging for Agent Decisions
3. Self-Healing Refactor Arena
4. Multi-Agent Architecture Design Review
5. Spec-to-Execution Trace Bridge
6. Instant Local Knowledge Graph Boot

## Recommended First Implementation
- Pick: Event Storm Control Room.
- Why:
  - highest combined visual impact + architecture authenticity
  - naturally demonstrates remora-v2's event-native core
  - supports a clean narrative arc (chaos -> orchestration -> convergence)

## Suggested 10-Minute Story Arc (for Top Pick)
1. Baseline: show steady-state event and node view.
2. Trigger: inject a controlled burst of changes.
3. Observe: watch proposals/actions fan out across agents.
4. Converge: show bounded stabilization and accepted outcomes.
5. Explain: replay one key decision from event log for credibility.
