"""HTML view templates for the Remora web surface."""


GRAPH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Remora - Agent Graph</title>
  <script src="https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"></script>
  <script src="https://unpkg.com/sigma@3.0.0-beta.31/build/sigma.min.js"></script>
  <script src="https://unpkg.com/graphology-layout-forceatlas2@0.10.1/build/graphology-layout-forceatlas2.min.js"></script>
  <style>
    :root {
      --bg: #f6f2ea;
      --panel: #ffffff;
      --ink: #1f1a16;
      --muted: #6f645c;
      --line: #d8cec3;
      --accent: #0f766e;
      --running: #ea580c;
      --done: #15803d;
      --error: #b91c1c;
      --function: #2563eb;
      --class: #7c3aed;
      --method: #0f766e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(1200px 800px at 10% 0%, #fff8ec, var(--bg));
      color: var(--ink);
      font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
      display: flex;
      min-height: 100vh;
    }
    #graph { flex: 1; min-height: 100vh; }
    #sidebar {
      width: min(440px, 92vw);
      border-left: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow-y: auto;
    }
    h1 { margin: 0 0 12px; font-size: 1.1rem; letter-spacing: 0.02em; }
    .meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 12px; }
    #node-details pre {
      max-height: 220px;
      overflow: auto;
      background: #f9f6f0;
      border: 1px solid var(--line);
      padding: 10px;
      border-radius: 8px;
      font-size: 0.8rem;
    }
    textarea, input, button {
      font-family: inherit;
      font-size: 0.9rem;
    }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      margin: 6px 0;
      background: #fffcf7;
    }
    button {
      border: 0;
      border-radius: 8px;
      padding: 8px 10px;
      cursor: pointer;
      background: var(--accent);
      color: white;
      margin-right: 6px;
    }
    button.secondary { background: #475569; }
    button.reject { background: #b91c1c; }
    #events {
      max-height: 180px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f9f6f0;
      padding: 8px;
      font-size: 0.82rem;
      white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <div id="graph"></div>
  <aside id="sidebar">
    <h1>Remora</h1>
    <div class="meta">Live swarm graph and companion panel</div>
    <section>
      <h2 id="node-name">Select a node</h2>
      <div id="node-details"></div>
    </section>
    <section>
      <h3>Chat</h3>
      <textarea id="chat-input" rows="4" placeholder="Ask selected node..."></textarea>
      <button id="send-chat">Send</button>
    </section>
    <section>
      <h3>Proposal</h3>
      <input id="proposal-id" placeholder="proposal_id" />
      <button id="approve" class="secondary">Approve</button>
      <button id="reject" class="reject">Reject</button>
    </section>
    <section>
      <h3>Events</h3>
      <div id="events"></div>
    </section>
  </aside>
  <script>
    const graph = new graphology.Graph();
    const renderer = new Sigma(graph, document.getElementById("graph"));
    let selectedNode = null;

    const colorByType = {
      function: getComputedStyle(document.documentElement).getPropertyValue("--function").trim(),
      class: getComputedStyle(document.documentElement).getPropertyValue("--class").trim(),
      method: getComputedStyle(document.documentElement).getPropertyValue("--method").trim()
    };

    function nodeColor(nodeType, status) {
      if (status === "running") {
        return getComputedStyle(document.documentElement)
          .getPropertyValue("--running")
          .trim();
      }
      if (status === "error") {
        return getComputedStyle(document.documentElement)
          .getPropertyValue("--error")
          .trim();
      }
      if (status === "idle") return colorByType[nodeType] || "#4f46e5";
      return getComputedStyle(document.documentElement).getPropertyValue("--done").trim();
    }

    async function loadGraph() {
      const nodesResp = await fetch("/api/nodes");
      const nodes = await nodesResp.json();
      for (const node of nodes) {
        if (!graph.hasNode(node.node_id)) {
          graph.addNode(node.node_id, {
            label: node.name,
            size: 8,
            x: Math.random(),
            y: Math.random(),
            color: nodeColor(node.node_type, node.status),
            node_type: node.node_type
          });
        }
      }
      for (const node of nodes) {
        const edgeResp = await fetch(`/api/nodes/${encodeURIComponent(node.node_id)}/edges`);
        const edges = await edgeResp.json();
        for (const edge of edges) {
          const key = `${edge.from_id}->${edge.to_id}:${edge.edge_type}`;
          if (!graph.hasNode(edge.from_id) || !graph.hasNode(edge.to_id)) continue;
          if (!graph.hasEdge(key)) {
            graph.addEdgeWithKey(key, edge.from_id, edge.to_id, { label: edge.edge_type, size: 1 });
          }
        }
      }
      if (window.graphologyLayoutForceatlas2) {
        window.graphologyLayoutForceatlas2.assign(graph, { iterations: 30 });
      }
      renderer.refresh();
    }

    function appendEventLine(text) {
      const box = document.getElementById("events");
      box.textContent = `${text}\n${box.textContent}`.slice(0, 4000);
    }

    async function showNode(nodeId) {
      const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`);
      if (!response.ok) return;
      const node = await response.json();
      document.getElementById("node-name").textContent = node.full_name;
      const details = document.getElementById("node-details");
      details.innerHTML = "";

      const typeDiv = document.createElement("div");
      typeDiv.textContent = `Type: ${node.node_type}`;
      details.appendChild(typeDiv);

      const statusDiv = document.createElement("div");
      statusDiv.textContent = `Status: ${node.status}`;
      details.appendChild(statusDiv);

      const fileDiv = document.createElement("div");
      fileDiv.textContent = `File: ${node.file_path}:${node.start_line}-${node.end_line}`;
      details.appendChild(fileDiv);

      const pre = document.createElement("pre");
      pre.textContent = node.source_code;
      details.appendChild(pre);
      selectedNode = node.node_id;
    }

    renderer.on("clickNode", ({ node }) => {
      showNode(node);
    });

    document.getElementById("send-chat").addEventListener("click", async () => {
      const message = document.getElementById("chat-input").value.trim();
      if (!selectedNode || !message) return;
      await fetch("/api/chat", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({ node_id: selectedNode, message })
      });
      document.getElementById("chat-input").value = "";
    });

    document.getElementById("approve").addEventListener("click", async () => {
      const proposalId = document.getElementById("proposal-id").value.trim();
      if (!proposalId) return;
      await fetch("/api/approve", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({ proposal_id: proposalId })
      });
    });

    document.getElementById("reject").addEventListener("click", async () => {
      const proposalId = document.getElementById("proposal-id").value.trim();
      if (!proposalId) return;
      await fetch("/api/reject", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({ proposal_id: proposalId })
      });
    });

    const evtSource = new EventSource('/sse');
    evtSource.addEventListener("NodeDiscoveredEvent", (event) => {
      const data = JSON.parse(event.data);
      if (!graph.hasNode(data.node_id)) {
        graph.addNode(data.node_id, {
          label: data.name || data.node_id.split("::").pop(),
          size: 8,
          x: Math.random(),
          y: Math.random(),
          node_type: data.node_type || "function",
          color: nodeColor(data.node_type || "function", "idle")
        });
      }
      renderer.refresh();
      appendEventLine(`NodeDiscoveredEvent: ${data.node_id}`);
    });
    evtSource.addEventListener("AgentStartEvent", (event) => {
      const data = JSON.parse(event.data);
      if (graph.hasNode(data.agent_id)) {
        graph.setNodeAttribute(data.agent_id, "color", nodeColor("", "running"));
        renderer.refresh();
      }
      appendEventLine(`AgentStartEvent: ${data.agent_id}`);
    });
    evtSource.addEventListener("AgentCompleteEvent", (event) => {
      const data = JSON.parse(event.data);
      if (graph.hasNode(data.agent_id)) {
        const nodeType = graph.getNodeAttribute(data.agent_id, "node_type");
        graph.setNodeAttribute(data.agent_id, "color", nodeColor(nodeType, "idle"));
        renderer.refresh();
      }
      appendEventLine(`AgentCompleteEvent: ${data.agent_id}`);
    });
    evtSource.addEventListener("AgentErrorEvent", (event) => {
      const data = JSON.parse(event.data);
      if (graph.hasNode(data.agent_id)) {
        graph.setNodeAttribute(data.agent_id, "color", nodeColor("", "error"));
        renderer.refresh();
      }
      appendEventLine(`AgentErrorEvent: ${data.agent_id}`);
    });
    evtSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        appendEventLine(`${payload.event_type || "Event"}: ${payload.correlation_id || ""}`);
      } catch {
        appendEventLine(event.data);
      }
    };

    loadGraph();
  </script>
</body>
</html>
"""


__all__ = ["GRAPH_HTML"]
