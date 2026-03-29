# Template Directory — 64-graph-ui-refactor

This template mirrors the target architecture from `GRAPH_IMPLEMENTATION_GUIDE.md` section 3.1.

## Tree

```text
.scratch/projects/64-graph-ui-refactor/template/
  src/remora/web/static/
    README.md
    graph-state.js
    layout-engine.js
    renderer.js
    interactions.js
    events.js
    panels.js
    main.js
```

## Notes

- Files are intentionally lightweight placeholders to speed the first implementation pass.
- The template does not modify production runtime by itself.
- Next migration step is copying/adapting these modules into `src/remora/web/static/` with compatibility wiring in `index.html`.
- Demo-repo checks are intentionally excluded from this scaffold per current project scope.
