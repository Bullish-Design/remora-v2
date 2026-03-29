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

function nodeSpacing(attrs) {
  const base = 16;
  const size = Number(attrs?.size || 8);
  const type = String(attrs?.node_type || "");
  const typeBonus = type === "class" ? 5 : (type === "virtual" ? 3 : 0);
  return base + size * 1.2 + typeBonus;
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
      const radius = 80 + uy * 260;
      graph.setNodeAttribute(nodeId, "x", Math.cos(angle) * radius);
      graph.setNodeAttribute(nodeId, "y", Math.sin(angle) * radius);
      index += 1;
    });
  }

  function relaxCollisions(graph, nodes, { rounds = 4 } = {}) {
    for (let round = 0; round < rounds; round += 1) {
      for (let i = 0; i < nodes.length; i += 1) {
        const aId = nodes[i];
        const a = graph.getNodeAttributes(aId);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const bId = nodes[j];
          const b = graph.getNodeAttributes(bId);
          const minDist = Math.max(nodeSpacing(a), nodeSpacing(b));
          let dx = Number(b.x) - Number(a.x);
          let dy = Number(b.y) - Number(a.y);
          let d = Math.sqrt(dx * dx + dy * dy);
          if (!Number.isFinite(d) || d < 0.0001) {
            dx = 0.01;
            dy = 0.01;
            d = 0.01;
          }
          if (d >= minDist) continue;
          const overlap = (minDist - d) / 2;
          const ux = dx / d;
          const uy = dy / d;
          if (!(pinnedNodeId && aId === pinnedNodeId)) {
            graph.setNodeAttribute(aId, "x", Number(a.x) - ux * overlap);
            graph.setNodeAttribute(aId, "y", Number(a.y) - uy * overlap);
          }
          if (!(pinnedNodeId && bId === pinnedNodeId)) {
            graph.setNodeAttribute(bId, "x", Number(b.x) + ux * overlap);
            graph.setNodeAttribute(bId, "y", Number(b.y) + uy * overlap);
          }
        }
      }
    }
  }

  function runForce(graph, {
    iterations = 80,
    repulsion = 7000,
    attraction = 0.005,
    gravity = 0.003,
    maxStep = 8.0,
    cooling = 0.99,
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
          const force = repulsion / Math.max(10, d2);
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

    relaxCollisions(graph, nodes, { rounds: 6 });
  }

  function runInitialLayout(graph, { iterations = 340 } = {}) {
    runForce(graph, {
      iterations,
      maxStep: 9.0,
      repulsion: 9000,
      attraction: 0.0048,
      gravity: 0.0025,
      cooling: 0.992,
    });
  }

  function reheatLayout(graph, { iterations = 110 } = {}) {
    runForce(graph, {
      iterations,
      maxStep: 4.6,
      repulsion: 6200,
      attraction: 0.0052,
      gravity: 0.0028,
      cooling: 0.989,
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
