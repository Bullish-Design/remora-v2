# Decisions — Embeddy Integration

## D1: No FTS5 baseline
Skip Approach F (FTS5-only). The plan covers only the embeddy SearchService integration. FTS5 can be a future enhancement.

## D2: Cover both remote and local modes
The plan should detail both remote (EmbeddyClient) and local (in-process Pipeline) modes in the SearchService.

## D3: Include Grail tool
Include `semantic_search.pym` as a core deliverable — it's a primary desired functionality for agents.

## D4: Include bootstrap indexing
Create a separate callable method for initial directory indexing (not just incremental). Include detail and explanation but not necessarily copy-pasteable code.

## D5: Test depth — detailed but not copy-pasteable
Include plenty of detail about what to test, test structure, mocking strategy, etc. but the intern writes the actual test code.

## D6: Use `embeddy[server]` in `search` and `dev` extras
While implementing Step 1, `from embeddy.client import EmbeddyClient` failed with `ModuleNotFoundError: fastapi` when only `embeddy` was installed. The current embeddy package executes `embeddy.__init__` and imports `embeddy.server`, which needs FastAPI. To preserve a working remote-mode import path and keep plan verification green, use `embeddy[server]` in `search` and `dev`.
