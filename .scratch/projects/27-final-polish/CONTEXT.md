# Context

- Proposals A and B complete and pushed.
- Proposal C complete: rewrite proposal events/status, `propose_changes` external, rewrite_self tool migration to workspace proposals, web proposal endpoints (list/diff/accept/reject), and runtime wiring of `workspace_service` into web app.
- Direct `apply_rewrite` external path removed; rewrites now follow workspace -> proposal -> human accept/reject flow.
- Next action: Proposal D (rich hover and LSP code actions/commands).
