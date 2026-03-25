# Assumptions

- The intended contract for downstream demo tooling is: `rewrite_accepted` then `content_changed` evidence.
- Proposal diff and file materialization logic are functionally correct today.
- Existing runtime event volume can be high, so assertions must avoid fragile global latest-event polling.
- We should avoid broad architectural changes (no event bus redesign) for this fix.
