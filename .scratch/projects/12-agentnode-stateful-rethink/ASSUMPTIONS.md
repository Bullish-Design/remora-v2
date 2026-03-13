# Assumptions

- The current actor loop and event store remain the foundation.
- AgentNode should be stateful first, conversational second.
- Human chat is one trigger type, not the default behavior for all triggers.
- Directory nodes should act as project/context experts, not generic chat bots.
- Short-term changes should be incremental and testable without rewriting the whole runtime.
- Strict tool input validation should remain in place.
