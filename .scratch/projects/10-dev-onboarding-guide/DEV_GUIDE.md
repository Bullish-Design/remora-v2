# Developer Guide

This section provides practical guidance for setting up your development environment, running the library, executing tests, and making changes to the remora-v2 codebase.

## Setting Up the Development Environment

### Prerequisites
Before you begin, ensure you have the following installed:

1. **Python 3.8+** - Remora v2 requires Python 3.8 or higher
2. **Git** - For cloning the repository and managing changes
3. **A C compiler** - Some dependencies (like tree-sitter) may require compilation
4. **Optional but recommended**: 
   - **Node.js** - For LSP-related development (if working on the LSP adapter)
   - **Docker** - For consistent environment reproduction
   - **PostgreSQL** - If you want to experiment with alternative storage (though SQLite is default)

### Getting the Code
```bash
# Clone the repository
git clone https://github.com/your-org/remora-v2.git
cd remora-v2
```

### Installing Dependencies
Remora v2 uses several modern Python tools for dependency management:

#### Using uv (Recommended)
```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

#### Using pip (Alternative)
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .
```

### Verifying the Installation
After installation, you should be able to run:
```bash
remora --help
```
This should display the CLI help text showing available commands like `start` and `discover`.

## Running the Library

### Basic Usage
Remora v2 is designed to run in the context of a project directory. Here's how to get started:

#### 1. Create a Configuration File
Create a `remora.yaml` file in your project root:
```yaml
# remora.yaml
project_path: "."
discovery_paths:
  - "src/"
  - "tests/"
discovery_languages: ["python"]
language_map:
  ".py": "python"
  ".md": "markdown"
  ".toml": "toml"
query_paths: ["queries/"]
workspace_ignore_patterns:
  - ".git"
  - "__pycache__"
  - ".venv"
  - "node_modules"
swarm_root: ".remora"
```

#### 2. Create Query Directories (Optional)
If you want to customize what gets discovered, create a `queries/` directory with `.scm` files:
```bash
mkdir -p queries
# Example: queries/python.scm
```
```scheme
; queries/python.scm
[
  (function_definition
    name: (identifier) @node.name) @node
  (class_definition
    name: (identifier) @node.name) @node
]
```

#### 3. Start Remora
```bash
# Start with web interface enabled (default port 8080)
remora start --project-root .

# Start without web interface
remora start --project-root . --no-web

# Run for a limited time (useful for testing)
remora start --project-root . --run-seconds 30

# Specify a custom config file
remora start --config /path/to/custom/remora.yaml
```

#### 4. Run Discovery Only
To see what Remora discovers without starting the full system:
```bash
remora discover --project-root .
```

### Understanding the Output
When Remora runs, you'll see log output showing:
- Discovery process identifying files and extracting code elements
- Agent creation for discovered elements
- Event processing as agents respond to changes
- Web server startup (if enabled)
- Any errors or warnings

The system creates a `.remora` directory in your project root for storing:
- SQLite database (`remora.db`)
- Agent workspaces (in `.remora/agents/`)
- Logs and other runtime data

## Running Tests

Remora v2 includes a comprehensive test suite to ensure correctness.

### Running All Tests
```bash
# Using pytest directly
pytest

# Or with uv
uv run pytest
```

### Running Specific Test Suites
```bash
# Run only unit tests
pytest tests/unit/

# Run tests for a specific component
pytest tests/unit/test_actor.py
pytest tests/unit/test_node.py

# Run tests with verbose output
pytest -v

# Run tests with coverage reporting
pytest --cov=remora tests/
```

### Understanding the Test Structure
The test suite follows this organization:
```
tests/
├── conftest.py          # Shared fixtures and configuration
├── unit/                # Unit tests for individual components
│   ├── test_actor.py
│   ├── test_node.py
│   ├── test_workspace.py
│   └── ... (many more)
└── integration/         # Integration tests (if any)
```

### Writing Tests
When adding new features or fixing bugs, follow these testing guidelines:

1. **Unit Tests**: Test individual functions or classes in isolation
   - Use mocks/patches for external dependencies
   - Focus on behavior, not implementation details
   - Test both happy paths and edge cases

2. **Integration Tests**: Test how components work together
   - Use real dependencies where reasonable
   - Test end-to-end scenarios
   - Be mindful of test execution time

3. **Test Naming**: Use descriptive names that indicate what is being tested
   - `test_actor_processes_inbox_message_success`
   - `test_node_store_returns_none_for_missing_id`
   - `test_event_matching_with_path_glob`

4. **Fixtures**: Use pytest fixtures for reusable setup
   - Look at `tests/conftest.py` for examples
   - Create component-specific fixtures in test files when needed

### Common Testing Tools
- **pytest**: The main testing framework
- **pytest-asyncio**: For testing async code (look for `@pytest.mark.asyncio`)
- **mock**: Part of standard library (`unittest.mock`) for replacing dependencies
- **factories**: Look for factory patterns in test files for creating test objects

## Making Changes to the Codebase

### Code Style Guidelines
Remora v2 follows these Python code style conventions:

#### Formatting
- **Line length**: Aim for 88 characters (default for Black/formatting tools)
- **Indentation**: 4 spaces (never tabs)
- **Imports**: 
  - Standard library imports first
  - Third-party imports second
  - Local application imports third
  - Each group separated by blank line
  - Within groups, sort alphabetically

#### Naming Conventions
- **Modules and files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions and methods**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private members**: `_snake_case` (single leading underscore)
- **Very private members**: `__snake_case` (double leading underscore - triggers name mangling)

#### Type Hints
- Use Python 3.8+ type hinting syntax
- Import typing constructs when needed: `from typing import Any, List, Dict, Optional`
- Use `from __future__ import annotations` at the top of files to enable postponed evaluation
- Prefer specific types over `Any` when possible
- Use `Optional[T]` instead of `Union[T, None]`

#### Documentation
- **Module docstrings**: Describe what the module provides
- **Class docstrings**: Explain the class's purpose and responsibilities
- **Method/docstrings**: Describe what the function does, parameters, return value, and exceptions
- **Inline comments**: Use sparingly for non-obvious logic or important notes
- **TODOs**: Use `# TODO:` format for tracking work that needs to be done

### Making Your First Change

Let's walk through a simple example of adding a new feature: adding a custom event type.

#### Step 1: Understand the Existing Pattern
Look at `src/remora/core/events/types.py` to see how events are defined:
```python
class AgentStartEvent(Event):
    agent_id: str
    node_name: str = ""
```

#### Step 2: Add Your New Event
Add a new event class to the same file:
```python
class CodeReviewRequestedEvent(Event):
    """Event emitted when requests a code review for a specific node."""
    agent_id: str
    node_id: str
    review_type: str = "general"  # e.g., "security", "performance", "style"
    requested_by: str | None = None  # Who requested the review
```

#### Step 3: Update the Exports
Add your new event to the `__all__` list at the end of the file:
```python
__all__ = [
    # ... existing events ...
    "CodeReviewRequestedEvent",
    # ... rest of exports ...
]
```

#### Step 4: Use Your New Event
Find where you want to emit this event (e.g., in the actor or reconciler) and add:
```python
from remora.core.events.types import CodeReviewRequestedEvent

# ... in some method ...
await self._event_store.append(
    CodeReviewRequestedEvent(
        agent_id=agent_id,
        node_id=node_id,
        review_type="security",
        requested_by="system"
    )
)
```

#### Step 5: Add Tests
Create a test in `tests/unit/test_events.py` (or create the file):
```python
def test_code_review_requested_event_creation():
    event = CodeReviewRequestedEvent(
        agent_id="test-agent",
        node_id="test.py::func",
        review_type="security"
    )
    assert event.agent_id == "test-agent"
    assert event.node_id == "test.py::func"
    assert event.review_type == "security"
    assert event.event_type == "CodeReviewRequestedEvent"  # Auto-set
```

#### Step 6: Run Tests to Verify
```bash
pytest tests/unit/test_events.py::test_code_review_requested_event_creation
```

### Common Development Tasks

#### Adding a New Language Plugin
1. Create a new file in `src/remora/code/languages/` (e.g., `javascript.py`)
2. Implement the `LanguagePlugin` interface
3. Register it in `LanguageRegistry` (usually automatic via discovery)
4. Add the appropriate `.scm` query file to your queries directory
5. Update `language_map` in your `remora.yaml` if needed

#### Modifying the Web Interface
1. Edit `src/remora/web/server.py` to add new API endpoints
2. Update `src/remora/web/static/index.html` for UI changes
3. Add new static assets as needed
4. Test by running the web interface and checking the API

#### Changing Agent Behavior
1. Modify `src/remora/core/actor.py` to change how agents process events
2. Update bundle configurations to change agent capabilities
3. Add or modify tool scripts in the bundle directories
4. Test by observing agent behavior in the web UI or logs

#### Extending Storage
1. Modify `src/remora/core/graph.py` to add new storage methods
2. Update table schemas in the `create_tables()` methods
3. Add migration scripts if needed for backward compatibility
4. Update callers in services and other components to use new functionality

### Debugging and Troubleshooting

#### Common Issues and Solutions

**Issue**: "ImportError: No module named 'tree_sitter'"
- **Solution**: Install the tree-sitter Python package: `pip install tree-sitter`
- May also need system-level dependencies for compiling bindings

**Issue**: Agents aren't triggering on file changes
- **Solution**: 
  - Check that the file is in a discovery path
  - Verify the file extension is mapped to a language in `language_map`
  - Check that the language plugin is available
  - Look at logs for discovery errors
  - Verify that subscriptions are set up correctly

**Issue**: Web interface not loading
- **Solution**:
  - Check that `--no-web` wasn't used
  - Verify the server is binding to the correct host/port
  - Check browser console for JavaScript errors
  - Ensure static files are being served correctly

**Issue**: Database is locked errors
- **Solution**:
  - Usually indicates multiple processes trying to write to SQLite simultaneously
  - Ensure you're not running multiple instances against the same database
  - Consider using WAL mode or switching to a client/server database for high concurrency

#### Useful Debugging Techniques

**Logging**:
- Adjust log levels via environment variables: `REMORA_LOG_LEVEL=debug remora start`
- Look for logger statements throughout the codebase
- Add temporary `logger.debug()` statements when troubleshooting

**Event Inspection**:
- Use the `/api/events` endpoint to see recent events
- Connect to the `/sse` endpoint to see real-time event stream
- Add breakpoints or print statements in event handlers

**Workspace Inspection**:
- Check the `.remora/agents/` directory to see agent workspaces
- Look at `_bundle/` directories for agent configurations and tools
- Examine agent-specific files to understand their environment

**Performance Profiling**:
- Use Python's built-in `cProfile` module
- Look for bottlenecks in discovery, reconciliation, or agent execution
- Consider profiling specific scenarios with realistic workloads

## Contributing Best Practices

When contributing to remora-v2, keep these principles in mind:

1. **Maintain the Event-Driven Paradigm**: Don't introduce tight coupling between components; use events for communication
2. **Preserve Isolation**: Keep agent workspaces isolated and respect security boundaries
3. **Think About Concurrency**: Consider how your changes affect the async nature of the system
4. **Keep It Simple**: Favor straightforward solutions over complex abstractions
5. **Write Tests**: Ensure new functionality is tested and existing tests still pass
6. **Update Documentation**: Keep docs in sync with code changes
7. **Follow Existing Patterns**: When in doubt, look at how similar problems were solved elsewhere in the codebase

## Getting Help

If you're stuck or need clarification:
1. **Check the existing documentation**: README.md, docstrings, and comments
2. **Look at the tests**: They often show how to use components correctly
3. **Review similar code**: See how other parts of the codebase solve similar problems
4. **Ask questions**: Reach out to maintainers or check issue trackers
5. **Experiment**: Sometimes the best way to understand is to try it and see what happens

## Next Steps

After you've gotten comfortable with the basics, consider:
1. **Exploring the deep dive analyses** in the `08-comprehensive-code-review` project for improvement ideas
2. **Trying to extend the system** with a new feature like custom event types or additional agent capabilities
3. **Looking at the architecture documentation** to understand how the pieces fit together
4. **Joining the community** to share your experiences and learn from others

Happy hacking with remora-v2!