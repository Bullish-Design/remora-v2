// Canonical graph-state model for incremental UI updates.

export function createGraphState() {
  const nodesById = new Map();
  const edgesByKey = new Map();

  function edgeKey(edge) {
    if (edge == null) return "";
    if (edge.id) return String(edge.id);
    return `${String(edge.from)}|${String(edge.type)}|${String(edge.to)}`;
  }

  function upsertNode(node) {
    if (!node || !node.id) return false;
    const id = String(node.id);
    const prev = nodesById.get(id);
    nodesById.set(id, { ...(prev || {}), ...node, id });
    return prev == null;
  }

  function upsertEdge(edge) {
    const key = edgeKey(edge);
    if (!key) return false;
    const prev = edgesByKey.get(key);
    edgesByKey.set(key, { ...(prev || {}), ...edge, __key: key });
    return prev == null;
  }

  function removeNode(nodeId) {
    const id = String(nodeId);
    const existed = nodesById.delete(id);
    if (!existed) return false;

    for (const [key, edge] of edgesByKey.entries()) {
      if (String(edge.from) === id || String(edge.to) === id) {
        edgesByKey.delete(key);
      }
    }
    return true;
  }

  function removeEdge(keyOrEdge) {
    const key = typeof keyOrEdge === "string" ? keyOrEdge : edgeKey(keyOrEdge);
    if (!key) return false;
    return edgesByKey.delete(key);
  }

  function applySnapshot(nodes, edges) {
    nodesById.clear();
    edgesByKey.clear();

    for (const node of nodes || []) upsertNode(node);
    for (const edge of edges || []) upsertEdge(edge);
  }

  function snapshot() {
    return {
      nodes: Array.from(nodesById.values()),
      edges: Array.from(edgesByKey.values()),
    };
  }

  return {
    nodesById,
    edgesByKey,
    edgeKey,
    upsertNode,
    upsertEdge,
    removeNode,
    removeEdge,
    applySnapshot,
    snapshot,
  };
}
