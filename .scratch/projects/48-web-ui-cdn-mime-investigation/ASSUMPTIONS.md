# ASSUMPTIONS

- The user wants an investigation and detailed explanation first; code changes are optional unless requested.
- The errors are observed in a modern browser enforcing `X-Content-Type-Options: nosniff`.
- The active page is served from `http://localhost:8080/` and loads `src/remora/web/static/index.html`.
- External CDN availability and packaging can change over time, so URL-level behavior should be verified directly.
