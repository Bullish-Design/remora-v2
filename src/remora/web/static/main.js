import { createGraphState } from "./graph-state.js";
import { createLayoutEngine } from "./layout-engine.js";
import { createRenderer } from "./renderer.js";
import { createInteractions } from "./interactions.js";
import { createEventStream } from "./events.js";
import { createPanels } from "./panels.js";

const graph = new graphology.Graph({ multi: true, type: "directed" });
const nodeLabelHitboxes = new Map();
const graphState = createGraphState();
const layoutEngine = createLayoutEngine();
const panels = createPanels(document);

const rendererApi = createRenderer({
  graph,
  container: document.getElementById("graph"),
  nodeLabelHitboxes,
});

const interactions = createInteractions({
  graph,
  renderer: rendererApi.renderer,
});

const runtimeMetrics = {
  mode: "graph",
  ready: false,
  full_reload_count: 0,
  incremental_batch_count: 0,
  incremental_event_count: 0,
  last_batch_size: 0,
  visible_nodes: 0,
  visible_edges: 0,
  hidden_by_thinning_count: 0,
  focus_mode: "full",
};
const uiState = {
  hasAutoFocusedAfterFirstSelection: false,
};

globalThis.graph = graph;
globalThis.renderer = rendererApi.renderer;
globalThis.nodeLabelHitboxes = nodeLabelHitboxes;
globalThis.__remora_layout_metrics = runtimeMetrics;

function nodeColor(nodeType, status) {
  const type = String(nodeType || "");
  const st = String(status || "idle");
  if (st === "running") return "#fb923c";
  if (st === "error") return "#f87171";
  if (st === "awaiting_input") return "#22d3ee";
  if (st === "awaiting_review") return "#fbbf24";
  if (type === "function") return "#60a5fa";
  if (type === "class") return "#a78bfa";
  if (type === "method") return "#22d3ee";
  if (type === "section") return "#fbbf24";
  if (type === "virtual") return "#f472b6";
  if (type === "table") return "#34d399";
  if (type === "directory") return "#64748b";
  return "#9fb2c8";
}

function baseNodeLabel(node) {
  if (!node) return "";
  return String(node.name || node.full_name || node.node_id || "");
}

function uniqueLabels(nodes) {
  const counts = new Map();
  for (const node of nodes) {
    const raw = baseNodeLabel(node);
    counts.set(raw, (counts.get(raw) || 0) + 1);
  }
  const labels = new Map();
  for (const node of nodes) {
    const raw = baseNodeLabel(node);
    if ((counts.get(raw) || 0) <= 1) {
      labels.set(node.node_id, raw);
      continue;
    }
    const file = String(node.file_path || "").split("/").filter(Boolean).slice(-2).join("/");
    labels.set(node.node_id, file ? `${raw} (${file})` : `${raw} (${node.node_id.slice(-10)})`);
  }
  return labels;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${url} -> ${response.status}`);
  }
  return await response.json();
}

function refreshFallbackHitboxes() {
  const ratio = rendererApi.renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
  if (!Number.isFinite(ratio) || ratio <= 0) return;
  if (nodeLabelHitboxes.size > 0) return;
  const dims = rendererApi.renderer.getDimensions();
  const graphRect = document.getElementById("graph")?.getBoundingClientRect() || null;
  const filterRect = document.getElementById("filter-bar")?.getBoundingClientRect() || null;
  graph.forEachNode((nodeId, attrs) => {
    if (attrs.hidden) return;
    const p = rendererApi.renderer.graphToViewport({ x: attrs.x, y: attrs.y });
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
    const label = String(attrs.label || nodeId);
    const width = Math.max(52, label.length * 7 + 16);
    const height = 22;
    const x = p.x - width / 2;
    const y = p.y - attrs.size - height - 4;
    if (x < 1 || y < 1 || x + width > dims.width - 1 || y + height > dims.height - 1) return;
    if (graphRect && filterRect) {
      const fx = filterRect.left - graphRect.left;
      const fy = filterRect.top - graphRect.top;
      const fw = filterRect.width;
      const fh = filterRect.height;
      const overlapW = Math.max(0, Math.min(x + width, fx + fw) - Math.max(x, fx));
      const overlapH = Math.max(0, Math.min(y + height, fy + fh) - Math.max(y, fy));
      if (overlapW > 0 && overlapH > 0) return;
    }
    nodeLabelHitboxes.set(nodeId, {
      x: x * ratio,
      y: y * ratio,
      width: width * ratio,
      height: height * ratio,
    });
  });
}

function syncVisibilityTelemetry() {
  const stats = interactions.getVisibilityStats?.();
  if (!stats) return;
  runtimeMetrics.visible_nodes = Number(stats.visibleNodes || 0);
  runtimeMetrics.visible_edges = Number(stats.visibleEdges || 0);
  runtimeMetrics.hidden_by_thinning_count = Number(stats.hiddenByThinning || 0);
  runtimeMetrics.focus_mode = String(stats.focusMode || "full");
}

function setFocusChips(mode) {
  document
    .querySelectorAll("[data-focus-mode]")
    .forEach((el) => el.classList.toggle("active", el.dataset.focusMode === mode));
}

function syncGraphFromState() {
  const desiredNodes = new Set(graphState.nodesById.keys());
  const desiredEdges = new Set(graphState.edgesByKey.keys());

  graph.forEachEdge((edgeId) => {
    if (!desiredEdges.has(edgeId)) graph.dropEdge(edgeId);
  });

  graph.forEachNode((nodeId) => {
    if (!desiredNodes.has(nodeId)) graph.dropNode(nodeId);
  });

  const labels = uniqueLabels(Array.from(graphState.nodesById.values()));

  for (const [nodeId, node] of graphState.nodesById.entries()) {
    const attrs = {
      node_id: nodeId,
      node_name: node.name || node.node_id,
      full_name: node.full_name || node.name || node.node_id,
      label: labels.get(nodeId) || node.name || nodeId,
      node_type: String(node.node_type || "function"),
      status: String(node.status || "idle"),
      file_path: node.file_path || "",
      start_line: Number(node.start_line || 0),
      end_line: Number(node.end_line || 0),
      text: node.text || "",
      color: nodeColor(node.node_type, node.status),
      size: node.node_type === "class" ? 9 : (node.node_type === "method" ? 7 : 8),
      forceLabel: true,
      hidden: false,
    };

    if (graph.hasNode(nodeId)) {
      for (const [key, value] of Object.entries(attrs)) {
        graph.setNodeAttribute(nodeId, key, value);
      }
      if (!Number.isFinite(Number(graph.getNodeAttribute(nodeId, "x")))) {
        graph.setNodeAttribute(nodeId, "x", 0);
      }
      if (!Number.isFinite(Number(graph.getNodeAttribute(nodeId, "y")))) {
        graph.setNodeAttribute(nodeId, "y", 0);
      }
    } else {
      graph.addNode(nodeId, { ...attrs, x: NaN, y: NaN });
    }
  }

  for (const [key, edge] of graphState.edgesByKey.entries()) {
    if (!graph.hasNode(edge.from_id) || !graph.hasNode(edge.to_id)) continue;
    const attrs = {
      label: String(edge.edge_type || "edge"),
      size: edge.edge_type === "imports" || edge.edge_type === "inherits" ? 2.2 : 1.2,
      color: edge.edge_type === "imports" ? "#6cc6ff" : (edge.edge_type === "inherits" ? "#ad97ff" : "#596d88"),
      is_cross_file: graph.getNodeAttribute(edge.from_id, "file_path") !== graph.getNodeAttribute(edge.to_id, "file_path"),
      is_context_tether: String(edge.edge_type || "") === "contains",
      hidden: false,
    };
    if (graph.hasEdge(key)) {
      for (const [attrKey, value] of Object.entries(attrs)) {
        graph.setEdgeAttribute(key, attrKey, value);
      }
    } else {
      graph.addDirectedEdgeWithKey(key, edge.from_id, edge.to_id, attrs);
    }
  }
}

async function refreshConversation(nodeId) {
  if (!nodeId) return;
  try {
    const payload = await getJson(`/api/nodes/${encodeURIComponent(nodeId)}/conversation`);
    panels.setConversation(payload.history || []);
  } catch (_err) {
    panels.setConversation([]);
  }
}

function selectNode(nodeId, { center = true } = {}) {
  if (!nodeId || !graph.hasNode(nodeId)) return;
  if (!uiState.hasAutoFocusedAfterFirstSelection && interactions.getState().focusMode === "full") {
    interactions.setFocusMode("hop1");
    setFocusChips("hop1");
    uiState.hasAutoFocusedAfterFirstSelection = true;
  }
  const attrs = graph.getNodeAttributes(nodeId);
  interactions.selectNode(nodeId);
  syncVisibilityTelemetry();
  layoutEngine.setPinnedNode(interactions.getState().pinSelected ? nodeId : null);
  panels.setNode({
    node_id: nodeId,
    name: attrs.node_name,
    full_name: attrs.full_name,
    file_path: attrs.file_path,
    node_type: attrs.node_type,
    status: attrs.status,
    start_line: attrs.start_line,
    end_line: attrs.end_line,
    text: attrs.text,
  });
  panels.setAgentHeader(attrs.full_name || attrs.node_name || nodeId);
  refreshConversation(nodeId);
  if (center) rendererApi.centerOnNode(nodeId, { animate: true });
}

function clearSelection() {
  interactions.clearSelection();
  syncVisibilityTelemetry();
  layoutEngine.setPinnedNode(null);
  panels.clearNodeSelection();
}

async function fullSnapshot({ fit = false } = {}) {
  const [nodes, edges] = await Promise.all([getJson("/api/nodes"), getJson("/api/edges")]);
  graphState.applySnapshot(nodes, edges);
  syncGraphFromState();
  layoutEngine.initializeLayout(graph, { seed: 42 });
  layoutEngine.runInitialLayout(graph, { iterations: 260 });
  interactions.applyVisibility();
  syncVisibilityTelemetry();
  rendererApi.refresh();
  requestAnimationFrame(refreshFallbackHitboxes);
  if (fit) rendererApi.fitVisible({ animate: false });
  runtimeMetrics.full_reload_count += 1;
}

async function upsertNodeIncremental(nodeId, { withRelationships = true } = {}) {
  const node = await getJson(`/api/nodes/${encodeURIComponent(nodeId)}`);
  graphState.upsertNode(node);
  if (withRelationships) {
    const rel = await getJson(`/api/nodes/${encodeURIComponent(nodeId)}/relationships`);
    for (const edge of rel || []) graphState.upsertEdge(edge);
  }
}

async function applyIncrementalBatch(batch) {
  let mutated = false;
  let needsResync = false;
  runtimeMetrics.incremental_batch_count += 1;
  runtimeMetrics.last_batch_size = batch.length;
  runtimeMetrics.incremental_event_count += batch.length;

  for (const item of batch) {
    const type = item.type;
    const payload = item.payload || {};

    try {
      if (type === "node_discovered") {
        await upsertNodeIncremental(payload.node_id, { withRelationships: true });
        mutated = true;
      } else if (type === "node_removed") {
        if (graphState.removeNode(payload.node_id)) mutated = true;
      } else if (type === "node_changed") {
        await upsertNodeIncremental(payload.node_id, { withRelationships: false });
        mutated = true;
      } else if (type === "content_changed") {
        // keep responsive in noisy content-update bursts without full reload
      } else if (type === "agent_start" || type === "agent_complete" || type === "agent_error") {
        const nodeId = String(payload.agent_id || "");
        const node = graphState.nodesById.get(nodeId);
        if (node) {
          if (type === "agent_start") node.status = "running";
          else if (type === "agent_complete") node.status = "idle";
          else node.status = "error";
          graphState.upsertNode(node);
          mutated = true;
        }
      }
    } catch (_err) {
      needsResync = true;
    }

    panels.appendEventLine(`${type}: ${JSON.stringify(payload)}`);
    panels.addTimelineEvent(type, payload);

    if (type === "agent_message") {
      const selected = interactions.getState().selectedNodeId;
      const toAgent = String(payload.to_agent || "");
      if (selected && toAgent === selected) {
        panels.appendAgentItem(
          String(payload.from_agent || "") === "user" ? "panel-user" : "panel-agent",
          String(payload.from_agent || "agent"),
          String(payload.content || ""),
        );
      }
    }

    if (type === "cursor_focus") {
      const focusId = String(payload.node_id || "").trim();
      if (focusId && graph.hasNode(focusId)) {
        selectNode(focusId, { center: true });
      }
    }
  }

  if (needsResync) {
    await fullSnapshot({ fit: false });
    return;
  }

  if (!mutated) return;

  const selectedBefore = interactions.getState().selectedNodeId;
  syncGraphFromState();
  layoutEngine.initializeLayout(graph, { seed: 42 });
  layoutEngine.reheatLayout(graph, { iterations: 70 });
  interactions.applyVisibility();
  syncVisibilityTelemetry();
  rendererApi.refresh();
  requestAnimationFrame(refreshFallbackHitboxes);

  if (selectedBefore && graph.hasNode(selectedBefore)) {
    rendererApi.ensureNodeVisible(selectedBefore);
  }
}

const events = createEventStream({
  onBatch: (batch) => {
    applyIncrementalBatch(batch).catch((err) => {
      console.error("incremental batch failed", err);
      fullSnapshot({ fit: false }).catch((err2) => {
        console.error("resync failed", err2);
      });
    });
  },
  onConnectionChange: (connected) => {
    panels.showConnectionStatus(connected);
  },
  batchWindowMs: 75,
});

function wireUiControls() {
  document.getElementById("zoom-in")?.addEventListener("click", () => {
    const camera = rendererApi.renderer.getCamera();
    const state = camera.getState();
    camera.animate({ ...state, ratio: state.ratio * 0.82 }, { duration: 180 });
  });

  document.getElementById("zoom-out")?.addEventListener("click", () => {
    const camera = rendererApi.renderer.getCamera();
    const state = camera.getState();
    camera.animate({ ...state, ratio: state.ratio * 1.22 }, { duration: 180 });
  });

  document.getElementById("zoom-reset")?.addEventListener("click", () => {
    rendererApi.fitVisible({ animate: true });
  });

  const filterBar = document.getElementById("filter-bar");
  filterBar?.addEventListener("click", (event) => {
    const chip = event.target.closest(".filter-chip");
    if (!chip) return;
    const nodeType = chip.dataset.filterNode;
    const edgeType = chip.dataset.filterEdge;
    const focusMode = chip.dataset.focusMode;
    const edgeEmphasis = chip.dataset.filterEdgeEmphasis;
    const tetherToggle = chip.dataset.filterTethers;
    const pinToggle = chip.dataset.pinToggle;

    if (nodeType) {
      interactions.toggleNodeType(nodeType);
      syncVisibilityTelemetry();
      chip.classList.toggle("active");
      return;
    }
    if (edgeType) {
      interactions.toggleEdgeType(edgeType);
      syncVisibilityTelemetry();
      chip.classList.toggle("active");
      return;
    }
    if (edgeEmphasis) {
      interactions.toggleCrossFileOnly();
      syncVisibilityTelemetry();
      chip.classList.toggle("active", interactions.getState().crossFileOnly);
      return;
    }
    if (tetherToggle) {
      interactions.toggleContextTethers();
      syncVisibilityTelemetry();
      chip.classList.toggle("active", interactions.getState().showContextTethers);
      return;
    }
    if (focusMode) {
      interactions.setFocusMode(focusMode);
      syncVisibilityTelemetry();
      setFocusChips(focusMode);
      return;
    }
    if (pinToggle) {
      const pinned = interactions.togglePin();
      syncVisibilityTelemetry();
      chip.classList.toggle("active", pinned);
      layoutEngine.setPinnedNode(pinned ? interactions.getState().selectedNodeId : null);
    }
  });

  const searchInput = document.getElementById("node-search");
  const runSearch = () => {
    const winner = interactions.searchNode(searchInput?.value || "");
    if (!winner) return;
    selectNode(winner, { center: true });
  };
  document.getElementById("search-go")?.addEventListener("click", runSearch);
  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSearch();
    }
  });

  const sendChat = async () => {
    const selected = interactions.getState().selectedNodeId;
    if (!selected) return;
    const input = document.getElementById("chat-input");
    const message = String(input?.value || "").trim();
    if (!message) return;

    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: selected, message }),
    });

    panels.appendAgentItem("panel-user", "user", message);
    if (input) input.value = "";
  };

  document.getElementById("send-chat")?.addEventListener("click", () => {
    sendChat().catch((err) => {
      console.error("chat failed", err);
      panels.appendAgentItem("panel-error", "error", String(err));
    });
  });
}

function wireRendererInteractions() {
  const selectFromLabelHitbox = (cssX, cssY) => {
    const ratio = rendererApi.renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
    const scaledX = cssX * ratio;
    const scaledY = cssY * ratio;
    for (const [nodeId, box] of nodeLabelHitboxes.entries()) {
      const inScaled =
        scaledX >= box.x
        && scaledX <= box.x + box.width
        && scaledY >= box.y
        && scaledY <= box.y + box.height;
      const boxCssX = box.x / ratio;
      const boxCssY = box.y / ratio;
      const boxCssW = box.width / ratio;
      const boxCssH = box.height / ratio;
      const inCss =
        cssX >= boxCssX
        && cssX <= boxCssX + boxCssW
        && cssY >= boxCssY
        && cssY <= boxCssY + boxCssH;
      if (!inScaled && !inCss) continue;
      if (!graph.hasNode(nodeId)) continue;
      selectNode(nodeId, { center: true });
      return true;
    }
    return false;
  };

  rendererApi.renderer.on("clickNode", ({ node }) => {
    if (graph.hasNode(node)) selectNode(node, { center: false });
  });

  rendererApi.renderer.on("clickEdge", ({ edge }) => {
    if (!graph.hasEdge(edge)) return;
    const attrs = graph.getEdgeAttributes(edge);
    const source = graph.source(edge);
    const target = graph.target(edge);
    panels.appendEventLine(`edge_click: ${attrs.label || "edge"} ${source} -> ${target}`);
  });

  rendererApi.renderer.on("clickStage", (event) => {
    if (selectFromLabelHitbox(event.x, event.y)) return;
    clearSelection();
  });

  const graphEl = document.getElementById("graph");
  graphEl?.addEventListener("click", (event) => {
    const rect = graphEl.getBoundingClientRect();
    const cssX = event.clientX - rect.left;
    const cssY = event.clientY - rect.top;
    if (selectFromLabelHitbox(cssX, cssY)) return;
    // Do not clear selection here: Sigma click handlers run on same gesture.
  });
}

async function start() {
  wireUiControls();
  wireRendererInteractions();

  await fullSnapshot({ fit: true });
  runtimeMetrics.ready = true;

  const requestedNode = new URLSearchParams(window.location.search).get("node");
  if (requestedNode && graph.hasNode(requestedNode)) {
    selectNode(requestedNode, { center: true });
  }

  events.start("/sse");
}

start().catch((err) => {
  console.error("failed to start web ui", err);
  panels.appendAgentItem("panel-error", "fatal", String(err));
});
