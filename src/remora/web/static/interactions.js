function bfsNeighborhood(graph, rootId, maxDepth) {
  const visited = new Set();
  const queue = [{ id: rootId, depth: 0 }];
  while (queue.length > 0) {
    const { id, depth } = queue.shift();
    if (visited.has(id)) continue;
    visited.add(id);
    if (depth >= maxDepth) continue;
    const neighbors = graph.neighbors(id) || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) queue.push({ id: neighbor, depth: depth + 1 });
    }
  }
  return visited;
}

export function createInteractions({ graph, renderer }) {
  const state = {
    selectedNodeId: null,
    focusMode: "full",
    hiddenNodeTypes: new Set(),
    hiddenEdgeTypes: new Set(),
    crossFileOnly: false,
    showContextTethers: true,
    pinSelected: false,
  };

  function selectedFocusSet() {
    if (!state.selectedNodeId || !graph.hasNode(state.selectedNodeId)) return null;
    if (state.focusMode === "hop1") return bfsNeighborhood(graph, state.selectedNodeId, 1);
    if (state.focusMode === "hop2") return bfsNeighborhood(graph, state.selectedNodeId, 2);
    return null;
  }

  function applyVisibility() {
    const focusSet = selectedFocusSet();
    const selectedId =
      state.selectedNodeId && graph.hasNode(state.selectedNodeId)
        ? state.selectedNodeId
        : null;
    const selectedNeighbors = selectedId ? bfsNeighborhood(graph, selectedId, 1) : null;

    graph.forEachNode((nodeId, attrs) => {
      const hiddenByType = state.hiddenNodeTypes.has(String(attrs.node_type || ""));
      const hiddenByFocus = focusSet ? !focusSet.has(nodeId) : false;
      graph.setNodeAttribute(nodeId, "hidden", hiddenByType || hiddenByFocus);
      graph.removeNodeAttribute(nodeId, "dimmed");
      graph.setNodeAttribute(nodeId, "is_selected", selectedId ? nodeId === selectedId : false);
      graph.setNodeAttribute(
        nodeId,
        "is_pinned",
        !!(state.pinSelected && selectedId && nodeId === selectedId),
      );
      graph.setNodeAttribute(
        nodeId,
        "is_focus_neighbor",
        !!(selectedNeighbors && nodeId !== selectedId && selectedNeighbors.has(nodeId)),
      );
    });

    const visibleEdgeCountEstimate = graph.edges().length;
    const thinLowSignal = visibleEdgeCountEstimate > 160;

    graph.forEachEdge((edgeId, attrs, sourceId, targetId) => {
      const hiddenByType = state.hiddenEdgeTypes.has(String(attrs.label || ""));
      const hiddenByCrossFile = state.crossFileOnly && !attrs.is_cross_file;
      const hiddenByTether = !state.showContextTethers && !!attrs.is_context_tether;
      const hiddenByThinning = thinLowSignal && String(attrs.label || "") === "contains";
      const hiddenByNode =
        (graph.hasNode(sourceId) && graph.getNodeAttribute(sourceId, "hidden")) ||
        (graph.hasNode(targetId) && graph.getNodeAttribute(targetId, "hidden"));
      graph.setEdgeAttribute(
        edgeId,
        "hidden",
        hiddenByType || hiddenByCrossFile || hiddenByTether || hiddenByThinning || hiddenByNode,
      );
      graph.removeEdgeAttribute(edgeId, "dimmed");
    });

    if (state.selectedNodeId && graph.hasNode(state.selectedNodeId)) {
      const keep = selectedNeighbors || bfsNeighborhood(graph, state.selectedNodeId, 1);
      graph.forEachNode((nodeId) => {
        graph.setNodeAttribute(nodeId, "dimmed", !keep.has(nodeId));
      });
      graph.forEachEdge((edgeId, attrs, sourceId, targetId) => {
        if (attrs.hidden) return;
        if (!keep.has(sourceId) || !keep.has(targetId)) {
          graph.setEdgeAttribute(edgeId, "dimmed", true);
        }
      });
    }

    renderer.refresh();
  }

  function selectNode(nodeId) {
    state.selectedNodeId = nodeId == null ? null : String(nodeId);
    applyVisibility();
  }

  function clearSelection() {
    state.selectedNodeId = null;
    state.pinSelected = false;
    applyVisibility();
  }

  function setFocusMode(mode) {
    state.focusMode = mode;
    applyVisibility();
  }

  function toggleNodeType(type) {
    if (state.hiddenNodeTypes.has(type)) state.hiddenNodeTypes.delete(type);
    else state.hiddenNodeTypes.add(type);
    applyVisibility();
  }

  function toggleEdgeType(type) {
    if (state.hiddenEdgeTypes.has(type)) state.hiddenEdgeTypes.delete(type);
    else state.hiddenEdgeTypes.add(type);
    applyVisibility();
  }

  function toggleCrossFileOnly() {
    state.crossFileOnly = !state.crossFileOnly;
    applyVisibility();
  }

  function toggleContextTethers() {
    state.showContextTethers = !state.showContextTethers;
    applyVisibility();
  }

  function togglePin() {
    state.pinSelected = !state.pinSelected;
    applyVisibility();
    return state.pinSelected;
  }

  function searchNode(query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return null;
    let winner = null;
    graph.forEachNode((nodeId, attrs) => {
      if (winner) return;
      const haystack = [nodeId, attrs.label, attrs.node_name, attrs.full_name, attrs.file_path]
        .filter(Boolean)
        .join("\n")
        .toLowerCase();
      if (haystack.includes(q)) winner = nodeId;
    });
    return winner;
  }

  function getState() {
    return {
      ...state,
      hiddenNodeTypes: new Set(state.hiddenNodeTypes),
      hiddenEdgeTypes: new Set(state.hiddenEdgeTypes),
    };
  }

  return {
    applyVisibility,
    selectNode,
    clearSelection,
    setFocusMode,
    toggleNodeType,
    toggleEdgeType,
    toggleCrossFileOnly,
    toggleContextTethers,
    togglePin,
    searchNode,
    getState,
  };
}
