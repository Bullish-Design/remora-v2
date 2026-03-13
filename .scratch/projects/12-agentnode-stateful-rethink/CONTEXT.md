# Context

## Current Status
A proposal-only project has been created to rethink AgentNode behavior. The report focuses on making internal state primary and chat responses conditional on trigger type.

## Why This Exists
Current runtime behavior executes full conversational turns for non-human triggers (for example NodeChangedEvent), causing repetitive narrative output from directory agents.

## Next Step
Review AGENT_PROPOSAL.md, choose a preferred option, then create an implementation plan and sequence of commits.
