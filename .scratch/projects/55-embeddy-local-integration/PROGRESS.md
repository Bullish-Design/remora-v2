# Progress

## Step Status
- [x] Read `LOCAL_EMBEDDY_MODEL_ENABLEMENT_OVERVIEW.md`
- [x] Audit remora-v2 search/runtime/API/index/test/doc paths
- [x] Validate embeddy-side root causes from `.context/embeddy`
- [x] Produce `EMBEDDY_EDITS_ANALYSIS.md`
- [x] Produce detailed `EMBEDDY_REFACTORING_GUIDE.md`

## Log
- Confirmed remora-v2 local mode currently marks search available without a local model load handshake.
- Confirmed `/api/search` has no backend exception mapping and can leak unstructured 500s.
- Confirmed `remora index` reports errors but always exits success after indexing loop.
- Confirmed local-mode collection handling is inconsistent with `collection_map`.
- Added step-by-step implementation guide for required embeddy + remora-v2 updates.
