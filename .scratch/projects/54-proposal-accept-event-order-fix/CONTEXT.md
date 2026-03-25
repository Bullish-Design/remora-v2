# Context

- Root cause identified: `api_proposal_accept` appends `content_changed` before `rewrite_accepted`, and reconciler reacts immediately to `content_changed`, creating ordering noise for demo proofs.
- Event retrieval endpoint returns newest-first bounded windows, which is fragile under high background traffic.
- Detailed fix guide is complete in `EVENT_ORDER_FIX_IMPLEMENTATION_GUIDE.md`.
- Next task: apply code and test changes from the guide.
