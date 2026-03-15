# Context — v1 → v2 Capability Gap Analysis

## Status: COMPLETE

The full analysis report has been written to `REPORT.md` in this directory.

## Summary

V2 achieves its goal of providing the same core functionality in a simpler mental model (72% code reduction, ~120 files → ~33 files). The companion system (MicroSwarms, sidebar composition, persistent chat agents) is the most significant missing capability. LSP richness and vector search are reduced but compensated by the web panel and text search respectively. All other "missing" features are either peripheral (browser demo, Docker deployment) or replaced by better abstractions (bootstrap → FileReconciler, extensions → bundle_rules, scattered DI → RuntimeServices).
