// Template panel renderer hooks for graph-side UI.

export function createPanels() {
  function renderNodeDetails(_node) {
    // TODO: render selected node metadata/details.
  }

  function renderTimeline(_events) {
    // TODO: render recent event feed.
  }

  function renderAgentStream(_messages) {
    // TODO: render chat/agent stream panel.
  }

  function clear() {
    // TODO: reset panel content.
  }

  return {
    renderNodeDetails,
    renderTimeline,
    renderAgentStream,
    clear,
  };
}
