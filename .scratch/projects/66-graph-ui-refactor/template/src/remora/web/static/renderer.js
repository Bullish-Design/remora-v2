// Template renderer facade for Sigma lifecycle and reducer wiring.

export function createRenderer() {
  let sigmaInstance = null;

  function initialize(_options = {}) {
    // TODO: create Sigma instance and register draw hooks/reducers.
  }

  function refresh() {
    if (!sigmaInstance) return;
    sigmaInstance.refresh();
  }

  function fit() {
    // TODO: camera fit policy should only be called on first load / explicit reset.
  }

  function centerOnNode(_nodeId) {
    // TODO: center camera around selected node while preserving zoom heuristics.
  }

  function destroy() {
    if (!sigmaInstance) return;
    sigmaInstance.kill();
    sigmaInstance = null;
  }

  return {
    initialize,
    refresh,
    fit,
    centerOnNode,
    destroy,
  };
}
