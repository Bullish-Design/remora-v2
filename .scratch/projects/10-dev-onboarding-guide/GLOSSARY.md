# Glossary of Key Terms and Concepts

This glossary defines important terms and concepts used throughout the remora-v2 codebase and documentation.

## A

**Agent**: An autonomous entity that can be attached to a code element to provide intelligent, reactive behavior. Agents process events in isolated workspaces and can execute actions based on their configuration and available tools.

**AgentActor**: The core implementation of an agent's processing loop. Each agent has its own AgentActor that processes events from its inbox sequentially.

**Agent Store**: The persistent storage component (AgentStore) that maintains the runtime status of all agents in the system.

**Agent Workspace**: An isolated filesystem environment provided to each agent, preventing interference between agents while allowing access to shared resources when needed.

**API (Application Programming Interface)**: The set of endpoints and protocols through which external systems can interact with remora-v2, primarily through the web interface.

**Append-only Event Log**: A data storage approach where events are only ever added, never modified or deleted. This provides an audit trail and enables rebuilding state by replaying events.

## B

**BaseModel**: The foundational Pydantic class used for defining data models with validation, serialization, and deserialization capabilities.

**Bundle**: A collection of configuration and tools that define how an agent should behave. Typically includes a system prompt, model selection, turn limits, and available tools.

**Bundle Configuration**: The YAML file (`_bundle/bundle.yaml`) that specifies an agent's behavior, including what LLM to use, what system prompt to follow, and how many turns to allow.

## C

**Code Element**: A discrete piece of code that has been discovered from source files, such as a function, class, method, or other language-specific construct.

**CodeNode**: A persistent representation of a discovered code element that includes both the immutable discovery data and mutable runtime status. (Note: In the current implementation, this combines concerns that might be better separated.)

**CSTNode (Concrete Syntax Tree Node)**: An immutable representation of a code element as discovered by the tree-sitter parsing process. Contains the raw information extracted from the source code.

**Concurrency Control**: Mechanisms used to limit how many agents can execute simultaneously, preventing resource overload. Implemented using asyncio.Semaphore in remora-v2.

**Configuration**: The user-definable settings that control how remora-v2 behaves, typically stored in remora.yaml and including discovery paths, language mappings, model settings, and more.

**Correlation ID**: A unique identifier used to group related events together, enabling tracing of causal chains through the system (e.g., an agent's processing of an event that triggers another agent).

## D

**Data Model**: A structured representation of information, typically implemented as a class with defined fields and behaviors. In remora-v2, these are primarily built using Pydantic.

**Discovery**: The process of parsing source files to identify code elements that can be represented as agents in the system.

**Event**: A factual record of something that has happened in the system. Events are the primary means of communication between components in remora-v2's event-driven architecture.

**Event Bus**: An in-memory publish/subscribe system that distributes events to interested subscribers in real-time.

**Event Store**: The persistent storage component that maintains a complete history of all events that have occurred in the system.

**Event-Driven Architecture**: A software architecture paradigm where the flow of the program is determined by events such as user actions, sensor outputs, or messages from other programs.

**Event Type**: A string identifier that categorizes what kind of event occurred (e.g., "AgentStartEvent", "NodeDiscoveredEvent").

## E

**Extension Point**: A location in the codebase where new functionality can be added without modifying existing code, such as through plugins or configuration.

**External Dependency**: A third-party library or system that remora-v2 relies on to provide certain functionality (e.g., tree-sitter for parsing, cairn for workspaces).

## F

**File Reconciler**: The component responsible for monitoring the filesystem for changes and keeping the internal graph of code elements in sync with what's actually on disk.

**Full Scan**: The initial process of discovering all code elements in the configured discovery paths when the system starts.

**Function Signature**: In the context of remora-v2, this often refers to the definition of a function including its name, parameters, and return type as discovered from source code.

## G

**Grail**: The integration system that allows remora-v2 to discover and make available external tools to agents, typically through language-server protocol or similar mechanisms.

## H

**Handler**: A function that processes events of a specific type. In the event system, handlers are registered to receive notifications when certain events occur.

**Hot Reload**: The ability to update the system's behavior without requiring a full restart. While not fully implemented, remora-v2 has elements that support runtime updates (e.g., changing bundle configurations).

## I

**Inbox**: The queue where an agent receives events to be processed. Each agent has its own inbox to ensure sequential processing.

**Incremental Reconciliation**: The process of checking for and processing only the files that have changed since the last check, rather than rescanning everything.

**Interface**: A shared boundary across which separate components of a system exchange information. In remora-v2, this includes the CLI, web interface, and LSP adapter.

**Isolation**: The principle of keeping different parts of the system separate so that failures or issues in one area don't negatively impact others. Agents are isolated through their individual workspaces.

## J

**JSON (JavaScript Object Notation)**: A lightweight data interchange format used extensively in remora-v2 for event payloads, API communication, and configuration.

## K

**Kernel**: The interface to Large Language Model (LLM) providers that enables agents to generate text, make decisions, and execute actions based on prompts and available tools.

**Key**: In the context of data structures, a unique identifier used to look up values in a map or dictionary.

## L

**Language Map**: A configuration that maps file extensions to language names for the purpose of discovery (e.g., ".py" maps to "python").

**Language Plugin**: An implementation that provides tree-sitter parsing capabilities for a specific language, including the grammar and query files.

**Lifecycle**: The sequence of states that an agent or code element goes through during its existence in the system (e.g., idle → running → complete/error → idle for agents).

**LLM (Large Language Model)**: An artificial intelligence model trained on vast amounts of text data that can understand and generate human-like text, used by agents for reasoning and action.

**Locality**: The principle of keeping related data and processing close together to minimize communication overhead and improve performance.

**Logical Time**: A concept used in distributed systems to order events without relying on physical clocks. In remora-v2, correlation IDs and sequences help establish logical ordering of related events.

## M

**Model**: In the context of remora-v2, this usually refers to either a Pydantic data model or a Large Language Model that agents use for reasoning.

**Module**: A file containing Python code that defines functions, classes, or variables that can be imported and used by other parts of the system.

**Mutability**: The ability to change an object's state after it has been created. Remora-v2 distinguishes between immutable data (discovered code elements) and mutable data (agent runtime status).

## N

**Node**: In remora-v2 terminology, this usually refers to a discovered code element that has been persisted in the system. Can sometimes be used ambiguously to refer to either the code element or its associated agent.

**Node Store**: The persistent storage component (NodeStore) that maintains information about all discovered code elements in the system.

**Notification**: A message sent to inform one or more parties about an event that has occurred. In remora-v2, events serve as notifications.

## O

**Observer Pattern**: A software design pattern in which an object (the subject) maintains a list of its dependents (observers) and notifies them automatically of any state changes, usually by calling one of their methods. The event system in remora-v2 is an implementation of this pattern.

**Outbox**: A pattern used in remora-v2 where events are created with metadata (like actor ID and correlation ID) and immediately written to the event store, providing a clean separation between event creation and persistence.

## P

**Persistence**: The characteristic of state that outlives the process that created it. Remora-v2 achieves persistence through SQLite storage.

**Projection**: The process of converting raw discoveries from tree-sitter (CSTNodes) into persistent system representations (CodeNodes).

**Provenance**: Information about the origin or history of something. In remora-v2, events contain provenance information like timestamps and correlation IDs.

**Publish/Subscribe (Pub/Sub)**: A messaging pattern where senders (publishers) categorize messages into classes without knowledge of who (if anyone) may receive them. Receivers (subscribers) express interest in one or more classes and only receive messages that are of interest.

## Q

**Query**: In the context of tree-sitter, a query is a pattern written in a special language that identifies specific nodes in a syntax tree to extract information from them.

**Query File**: A file with a .scm extension that contains tree-sitter queries defining what code elements to discover from source files.

## R

**Reconciliation**: The process of ensuring that two sets of data are consistent with each other. In remora-v2, this refers to keeping the internal graph of code elements synchronized with the actual files on disk.

**Reflection**: The ability of a program to examine, introspect, and modify its own structure and behavior at runtime. While limited, remora-v2 has some reflective capabilities through its event system and APIs.

**Registry**: A central repository for keeping track of items of a certain type. Examples in remora-v2 include the LanguageRegistry (for language plugins) and SubscriptionRegistry (for event routing rules).

**Resource**: Anything that is limited and must be managed carefully, such as CPU time, memory, or API rate limits. Remora-v2 manages concurrency through semaphores to prevent resource exhaustion.

**Response**: The result or output produced by an agent after processing an event, typically emitted as an AgentCompleteEvent or AgentErrorEvent.

## S

**Schema**: The structure that defines how data is organized, particularly in databases or data models. In remora-v2, this refers to both Pydantic model definitions and SQL table schemas.

**Semaphore**: A synchronization primitive used to control access to a common resource by multiple processes in a concurrent system. Remora-v2 uses asyncio.Semaphore to limit how many agents can execute simultaneously.

**Separation of Concerns**: A design principle for separating a computer program into distinct sections such that each section addresses a separate concern. A key goal in software architecture to improve maintainability and clarity.

**Serial Processing**: Handling items one at a time in sequence, rather than in parallel. Agents in remora-v2 process events serially from their inboxes to avoid race conditions.

**State**: The current condition or status of a system or component at a particular point in time. In remora-v2, this includes things like what code elements have been discovered, what agents exist, and what their current statuses are.

**Status Transition**: A change from one state to another that is governed by specific rules (e.g., an agent can only go from IDLE to RUNNING, not directly from IDLE to ERROR).

**Subscription**: A declaration of interest in receiving certain types of events. Agents subscribe to events they want to respond to, and the system delivers matching events to their inboxes.

**Subscription Pattern**: A set of criteria used to determine whether an event should be delivered to a particular subscriber. Can filter by event type, source/destination agents, file paths, and more.

**System**: In the context of remora-v2, this usually refers to the overall reactive agent substrate that provides the infrastructure for discovering code elements and executing agents.

## T

**Tree-sitter**: A parser generator tool and incremental parsing library that can build concrete syntax trees for source code and efficiently update them as the file is edited. Used by remora-v2 for multi-language code discovery.

**Turn**: In the context of agent execution with an LLM, a turn typically refers to one cycle of interaction: the agent receives input (prompt + tool results), generates output, and potentially executes tools based on that output.

**Type Safety**: The extent to which a programming language prevents type errors. Remora-v2 uses Python's type hints and Pydantic validation to achieve a high degree of type safety.

## U

**Use Case**: A specific scenario in which the system is used to achieve a particular goal. Examples in remora-v2 include automated code review, live documentation generation, and dependency tracking.

## V

**Validation**: The process of checking that data conforms to expected rules or constraints. Remora-v2 uses Pydantic validation extensively to ensure data integrity.

**Version**: A particular iteration or release of the software. While not explicitly tracked in this glossary, remora-v2 follows semantic versioning principles.

**View**: A representation of data tailored for a particular purpose or audience. The web interface provides various views of the system state (graph view, event view, etc.).

## W

**Watchman**: A term sometimes used in file watching systems to refer to the process or component that monitors files for changes. In remora-v2, this role is played by the FileReconciler using the watchfiles library.

**Web Interface**: The browser-accessible dashboard provided by remora-v2 that allows users to visualize the code graph, view events, and interact with agents.

**Worker**: A term sometimes used synonymously with agent or Actor to refer to an entity that performs work. In remora-v2, agents are the workers that process events and execute actions.

**Wrapper**: A thin layer of code that provides a simplified interface to a more complex underlying system. The db.py file provides a wrapper around SQLite database operations.

## X

**XML (eXtensible Markup Language)**: A markup language that defines a set of rules for encoding documents in a format that is both human-readable and machine-readable. Not heavily used in remora-v2, which prefers JSON for data interchange.

## Y

**YAML (YAML Ain't Markup Language)**: A human-readable data serialization standard that can be used in conjunction with all programming languages and is often used for configuration files. Remora-v2 uses YAML for remora.yaml and bundle configuration files.

## Z

**Zero Configuration**: The ideal of requiring no setup to get a system running. While remora-v2 requires some configuration (discovery paths, etc.), it strives to minimize the amount of setup needed through sensible defaults and convention over configuration.

**Zone**: In the context of isolation or security, a zone refers to a restricted area where certain rules apply. Agent workspaces in remora-v2 can be thought of as security zones with controlled access.

--- 

*This glossary is a living document. As you work with remora-v2, you may encounter terms not listed here. Feel free to add them to your personal copy or contribute them back to improve the documentation for future developers.*