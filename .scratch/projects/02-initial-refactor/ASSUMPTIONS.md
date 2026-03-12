# Assumptions

## Project Audience
- The project author/maintainer. Refactor must preserve existing test behavior where not intentionally changed.

## Scope
- Refactor guided by the code review findings in `01-initial-code-review/CODE_REVIEW.md`
- Primary focus: replace ast-based Python-only discovery with tree-sitter multi-language discovery
- Secondary focus: fix critical/high bugs identified in the review
- Tertiary: design/architecture improvements that naturally fall out of the refactor

## Constraints
- tree-sitter is already a hard dependency (`tree-sitter>=0.24` in pyproject.toml)
- `CSTNode` and `CodeNode` models are the public interface — changes must be deliberate
- Custom deps (cairn, grail, structured_agents) are stable — don't refactor their interfaces
- Python 3.13+ required
- TDD: write failing tests first, then implement

## Key Decisions Pending
- Which tree-sitter language grammars to ship/require
- Config schema for filetype→language mapping and node type selection
- Whether `.scm` query files ship in the package or are user-configurable
- How non-code files (markdown, toml) map to "node" concepts
- Which code review bugs to bundle into this refactor vs. separate PRs
