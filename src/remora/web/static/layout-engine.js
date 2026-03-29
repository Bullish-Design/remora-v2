function hashUnit(input) {
  let h = 2166136261;
  const text = String(input ?? "");
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const positive = h >>> 0;
  return positive / 4294967295;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function createLayoutEngine() {
  let pinnedNodeId = null;

  function initializeLayout(graph, { seed = 42 } = {}) {
    let index = 0;
    graph.forEachNode((nodeId, attrs) => {
      if (attrs.node_type === "__label__") return;
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (Number.isFinite(x) && Number.isFinite(y)) return;
      const ux = hashUnit(`${seed}:${nodeId}:x:${index}`);
      const uy = hashUnit(`${seed}:${nodeId}:y:${index}`);
      const angle = ux * Math.PI * 2;
      const radius = 20 + uy * 80;
      graph.setNodeAttribute(nodeId, "x", Math.cos(angle) * radius);
      graph.setNodeAttribute(nodeId, "y", Math.sin(angle) * radius);
      index += 1;
    });
  }

  function runForce(graph, {
    iterations = 80,
    repulsion = 1800,
    attraction = 0.008,
    gravity = 0.015,
    maxStep = 2.2,
    cooling = 0.985,
  } = {}) {
    const nodes = graph.nodes().filter((id) => {
      const attrs = graph.getNodeAttributes(id);
      return attrs.node_type !== "__label__" && !attrs.hidden;
    });
    if (nodes.length <= 1) return;

    const disp = new Map();
    let temperature = maxStep;

    for (let iter = 0; iter < iterations; iter += 1) {
      for (const id of nodes) {
        disp.set(id, { x: 0, y: 0 });
      }

      for (let i = 0; i < nodes.length; i += 1) {
        const aId = nodes[i];
        const a = graph.getNodeAttributes(aId);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const bId = nodes[j];
          const b = graph.getNodeAttributes(bId);
          let dx = Number(a.x) - Number(b.x);
          let dy = Number(a.y) - Number(b.y);
          let d2 = dx * dx + dy * dy;
          if (!Number.isFinite(d2) || d2 < 0.0001) {
            dx = 0.01;
            dy = 0.01;
            d2 = 0.0002;
          }
          const d = Math.sqrt(d2);
          const force = repulsion / d2;
          const fx = (dx / d) * force;
          const fy = (dy / d) * force;

          const ad = disp.get(aId);
          const bd = disp.get(bId);
          ad.x += fx;
          ad.y += fy;
          bd.x -= fx;
          bd.y -= fy;
        }
      }

      graph.forEachEdge((edgeId, edge) => {
        const sourceId = graph.source(edgeId);
        const targetId = graph.target(edgeId);
        if (!disp.has(sourceId) || !disp.has(targetId)) return;
        if (edge.hidden) return;
        const s = graph.getNodeAttributes(sourceId);
        const t = graph.getNodeAttributes(targetId);
        let dx = Number(t.x) - Number(s.x);
        let dy = Number(t.y) - Number(s.y);
        let d = Math.sqrt(dx * dx + dy * dy);
        if (!Number.isFinite(d) || d < 0.0001) d = 0.0001;
        const force = d * attraction;
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        const sd = disp.get(sourceId);
        const td = disp.get(targetId);
        sd.x += fx;
        sd.y += fy;
        td.x -= fx;
        td.y -= fy;
      });

      for (const id of nodes) {
        if (pinnedNodeId && id === pinnedNodeId) continue;
        const attrs = graph.getNodeAttributes(id);
        const d = disp.get(id);
        d.x -= Number(attrs.x) * gravity;
        d.y -= Number(attrs.y) * gravity;
        const stepX = clamp(d.x, -temperature, temperature);
        const stepY = clamp(d.y, -temperature, temperature);
        graph.setNodeAttribute(id, "x", Number(attrs.x) + stepX);
        graph.setNodeAttribute(id, "y", Number(attrs.y) + stepY);
      }

      temperature *= cooling;
    }
  }

  function runInitialLayout(graph, { iterations = 280 } = {}) {
    runForce(graph, { iterations, maxStep: 3.0, repulsion: 2400, attraction: 0.009 });
  }

  function reheatLayout(graph, { iterations = 70 } = {}) {
    runForce(graph, {
      iterations,
      maxStep: 1.6,
      repulsion: 1700,
      attraction: 0.008,
      gravity: 0.012,
      cooling: 0.98,
    });
  }

  function setPinnedNode(nodeId) {
    pinnedNodeId = nodeId == null ? null : String(nodeId);
  }

  function getPinnedNode() {
    return pinnedNodeId;
  }

  function disposeLayout() {
    pinnedNodeId = null;
  }

  return {
    initializeLayout,
    runInitialLayout,
    reheatLayout,
    setPinnedNode,
    getPinnedNode,
    disposeLayout,
  };
}
