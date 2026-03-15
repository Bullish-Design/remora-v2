# Assumptions - 23-demo-analysis-review

1. Primary objective is a high-confidence live demo for stakeholders, not backward compatibility.
2. "Demo-ready" means repeatable behavior in real runtime conditions with acceptable latency and clear visual storytelling.
3. Existing production code should be analyzed as-is; this project is analysis/reporting, not immediate feature implementation.
4. A vLLM endpoint at `http://remora-server:8000/v1` is the intended model backend for full demos.
5. Neovim + Web UI side-by-side is the target demo experience based on the existing demo plan.
