# Context — 21-virtual-agent-implementation

Virtual agent layer has been implemented and verified.

Implemented:
- `NodeType.VIRTUAL`
- `Config.virtual_agents` schema with validated declarative subscriptions
- Reconciler bootstrap/sync for virtual nodes (create/update/remove)
- Virtual agent subscription registration + bundle provisioning
- Actor prompt branch for virtual nodes (`## Role` framing)
- New bundles: `bundles/test-agent`, `bundles/review-agent`
- Example config documentation in `remora.yaml.example`
- Unit/integration tests for config parsing, reconciler bootstrap, prompt behavior, and real LLM reactive execution

Verification:
- Real vLLM integration run against `http://remora-server:8000/v1` passed.
- Full test suite passed with real integration enabled (`212 passed`).

Next:
- Commit all changes and push.
