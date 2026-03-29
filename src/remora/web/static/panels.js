function escHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (_err) {
    return String(value);
  }
}

export function createPanels(doc = document) {
  const nodeNameEl = doc.getElementById("node-name");
  const nodeDetailsEl = doc.getElementById("node-details");
  const agentHeaderEl = doc.getElementById("agent-header");
  const agentStreamEl = doc.getElementById("agent-stream");
  const eventsEl = doc.getElementById("events");
  const timelineEl = doc.getElementById("timeline-container");
  const statusEl = doc.getElementById("connection-status");

  function showConnectionStatus(connected) {
    if (!statusEl) return;
    statusEl.classList.toggle("connected", connected);
    statusEl.classList.toggle("disconnected", !connected);
  }

  function setNode(node) {
    if (nodeNameEl) {
      nodeNameEl.textContent = node ? (node.full_name || node.name || node.node_id) : "Select a node";
    }
    if (!nodeDetailsEl) return;
    if (!node) {
      nodeDetailsEl.innerHTML = "";
      return;
    }
    const summary = [
      `id: ${node.node_id}`,
      `type: ${node.node_type}`,
      `status: ${node.status || "idle"}`,
      `file: ${node.file_path || ""}`,
      `lines: ${node.start_line ?? "?"}-${node.end_line ?? "?"}`,
    ].join("\n");
    nodeDetailsEl.innerHTML = `<pre>${escHtml(summary)}\n\n${escHtml(node.text || "")}</pre>`;
  }

  function setAgentHeader(text) {
    if (agentHeaderEl) agentHeaderEl.textContent = text;
  }

  function appendAgentItem(kind, title, body) {
    if (!agentStreamEl) return;
    const block = doc.createElement("div");
    block.className = `panel-item ${kind}`;
    const head = doc.createElement("div");
    head.className = "panel-meta";
    head.textContent = title;
    const content = doc.createElement("div");
    content.textContent = body;
    block.appendChild(head);
    block.appendChild(content);
    agentStreamEl.prepend(block);
  }

  function setConversation(messages) {
    if (!agentStreamEl) return;
    agentStreamEl.innerHTML = "";
    for (const item of messages || []) {
      const role = String(item.role || "agent");
      const kind = role === "user" ? "panel-user" : "panel-agent";
      appendAgentItem(kind, role, String(item.content || ""));
    }
  }

  function appendEventLine(line) {
    if (!eventsEl) return;
    const lines = eventsEl.textContent ? eventsEl.textContent.split("\n") : [];
    lines.push(line);
    eventsEl.textContent = lines.slice(-120).join("\n");
    eventsEl.scrollTop = eventsEl.scrollHeight;
  }

  function addTimelineEvent(type, payload) {
    if (!timelineEl) return;
    const row = doc.createElement("div");
    row.className = `timeline-event type-${type}`;
    const kind = doc.createElement("div");
    kind.className = "timeline-type";
    kind.textContent = type;
    const meta = doc.createElement("div");
    meta.className = "timeline-meta";
    meta.textContent = pretty(payload);
    row.appendChild(kind);
    row.appendChild(meta);
    timelineEl.prepend(row);
    while (timelineEl.childElementCount > 120) {
      timelineEl.removeChild(timelineEl.lastElementChild);
    }
  }

  function clearNodeSelection() {
    setNode(null);
    setAgentHeader("(select a node)");
  }

  return {
    showConnectionStatus,
    setNode,
    setAgentHeader,
    appendAgentItem,
    setConversation,
    appendEventLine,
    addTimelineEvent,
    clearNodeSelection,
  };
}
