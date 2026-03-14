# Assumptions — 21-virtual-agent-implementation

- Config declarations are authoritative for managed virtual agents.
- Virtual agents should keep direct-message subscription (`to_agent=<id>`) plus configured patterns.
- Virtual agents do not participate in CST directory hierarchy (`parent_id=None`).
- Real integration verification will run against `http://remora-server:8000/v1` using existing test model env vars.
