# Context

Project created to implement P0/P1 recommendations from project 29 doc.

Current status:
- Item 1 complete: path traversal prevention in proposal diff/accept disk path resolution.
- Added root-confinement validation and 400 responses for invalid proposal workspace paths.
- Added unit tests for traversal attempts in both diff and accept endpoints.
- Item 2 complete: CSRF Origin validation middleware for mutating web API methods.
- Added unit tests for rejected non-local origin and allowed localhost origin.

Next:
- Implement item 3: Actor `_depths` TTL cleanup.
- Keep one-item-per-commit and push after each item.
