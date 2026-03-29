// Template interaction controller for focus/filter/search/pinning behavior.

export function createInteractions() {
  const state = {
    selectedNodeId: null,
    focusMode: "full", // full | hop1 | hop2
    nodeTypeFilters: new Set(),
    edgeTypeFilters: new Set(),
    pinSelected: false,
  };

  function selectNode(nodeId) {
    state.selectedNodeId = nodeId == null ? null : String(nodeId);
  }

  function setFocusMode(mode) {
    state.focusMode = mode;
  }

  function setPinSelected(enabled) {
    state.pinSelected = Boolean(enabled);
  }

  function clearSelection() {
    state.selectedNodeId = null;
    state.pinSelected = false;
  }

  function getState() {
    return {
      ...state,
      nodeTypeFilters: new Set(state.nodeTypeFilters),
      edgeTypeFilters: new Set(state.edgeTypeFilters),
    };
  }

  return {
    selectNode,
    setFocusMode,
    setPinSelected,
    clearSelection,
    getState,
  };
}
