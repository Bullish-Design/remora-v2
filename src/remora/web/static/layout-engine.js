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

function estimateLabelWidth(attrs) {
  const text = String(attrs?.label || attrs?.node_name || attrs?.full_name || "");
  if (!text) return 56;
  return Math.max(56, Math.min(300, text.length * 7 + 18));
}

function nodeSpacing(graph, nodeId, attrs) {
  const base = 20;
  const size = Number(attrs?.size || 8);
  const type = String(attrs?.node_type || "");
  const typeBonus =
    type === "class"
      ? 13
      : (type === "method" ? 9 : (type === "function" ? 8 : (type === "virtual" ? 10 : 6)));
  const degree = Number(graph.degree?.(nodeId) || 0);
  const degreeBonus = Math.min(18, Math.sqrt(Math.max(0, degree)) * 5);
  const labelBonus = Math.min(44, estimateLabelWidth(attrs) * 0.16);
  return base + size * 1.4 + typeBonus + degreeBonus + labelBonus;
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

  function relaxCollisions(
    graph,
    nodes,
    {
      minRounds = 8,
      maxRounds = 22,
      targetAverageOverlap = 0.045,
    } = {},
  ) {
    let previousAverage = Number.POSITIVE_INFINITY;
    for (let round = 0; round < maxRounds; round += 1) {
      let collisions = 0;
      let overlapBudget = 0;
      for (let i = 0; i < nodes.length; i += 1) {
        const aId = nodes[i];
        const a = graph.getNodeAttributes(aId);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const bId = nodes[j];
          const b = graph.getNodeAttributes(bId);
          const minDist = Math.max(
            nodeSpacing(graph, aId, a),
            nodeSpacing(graph, bId, b),
          );
          let dx = Number(b.x) - Number(a.x);
          let dy = Number(b.y) - Number(a.y);
          let d = Math.sqrt(dx * dx + dy * dy);
          if (!Number.isFinite(d) || d < 0.0001) {
            const jitter = (hashUnit(`${aId}:${bId}:${round}`) - 0.5) * 0.5;
            dx = 0.02 + jitter;
            dy = 0.02 - jitter;
            d = Math.sqrt(dx * dx + dy * dy);
          }
          if (d >= minDist) continue;
          collisions += 1;
          const overlap = minDist - d;
          overlapBudget += overlap / minDist;
          const push = overlap * 0.52;
          const ux = dx / d;
          const uy = dy / d;
          if (!(pinnedNodeId && aId === pinnedNodeId)) {
            graph.setNodeAttribute(aId, "x", Number(a.x) - ux * push);
            graph.setNodeAttribute(aId, "y", Number(a.y) - uy * push);
          }
          if (!(pinnedNodeId && bId === pinnedNodeId)) {
            graph.setNodeAttribute(bId, "x", Number(b.x) + ux * push);
            graph.setNodeAttribute(bId, "y", Number(b.y) + uy * push);
          }
        }
      }
      const averageOverlap = collisions > 0 ? overlapBudget / collisions : 0;
      const roundsMet = round + 1 >= minRounds;
      if (!roundsMet) {
        previousAverage = averageOverlap;
        continue;
      }
      if (averageOverlap <= targetAverageOverlap) break;
      if (averageOverlap >= previousAverage - 0.0015) break;
      previousAverage = averageOverlap;
    }
  }

  function normalizeViewportSpread(
    graph,
    nodes,
    {
      minFill = 0.7,
      maxFill = 0.85,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 2) return;

    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let sumX = 0;
    let sumY = 0;
    let spacingSum = 0;
    let count = 0;

    for (const nodeId of nodes) {
      if (!graph.hasNode(nodeId)) continue;
      const attrs = graph.getNodeAttributes(nodeId);
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      sumX += x;
      sumY += y;
      spacingSum += nodeSpacing(graph, nodeId, attrs);
      count += 1;
    }

    if (count < 2) return;

    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);
    const centerX = sumX / count;
    const centerY = sumY / count;
    const avgSpacing = spacingSum / count;
    const targetScale = Math.sqrt(count);
    const targetWidth = Math.max(340, targetScale * avgSpacing * 2.65);
    const targetHeight = Math.max(280, targetScale * avgSpacing * 2.15);
    const fillX = spanX / targetWidth;
    const fillY = spanY / targetHeight;
    let scale = 1;

    if (fillX < minFill || fillY < minFill) {
      const needX = fillX < minFill ? minFill / Math.max(0.0001, fillX) : 1;
      const needY = fillY < minFill ? minFill / Math.max(0.0001, fillY) : 1;
      scale = Math.max(needX, needY);
    } else if (fillX > maxFill || fillY > maxFill) {
      const trimX = fillX > maxFill ? maxFill / fillX : 1;
      const trimY = fillY > maxFill ? maxFill / fillY : 1;
      scale = Math.min(trimX, trimY);
    }

    if (!Number.isFinite(scale) || Math.abs(scale - 1) < 0.01) return;

    for (const nodeId of nodes) {
      if (!graph.hasNode(nodeId)) continue;
      if (pinnedNodeId && nodeId === pinnedNodeId) continue;
      const attrs = graph.getNodeAttributes(nodeId);
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      graph.setNodeAttribute(nodeId, "x", centerX + (x - centerX) * scale);
      graph.setNodeAttribute(nodeId, "y", centerY + (y - centerY) * scale);
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

    relaxCollisions(graph, nodes, {
      minRounds: 10,
      maxRounds: 26,
      targetAverageOverlap: 0.04,
    });
    normalizeViewportSpread(graph, nodes, {
      minFill: 0.72,
      maxFill: 0.84,
    });
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
