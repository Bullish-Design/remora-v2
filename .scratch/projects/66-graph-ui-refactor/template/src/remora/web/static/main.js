import { createGraphState } from "./graph-state.js";
import { createLayoutEngine } from "./layout-engine.js";
import { createRenderer } from "./renderer.js";
import { createInteractions } from "./interactions.js";
import { createEventRouter } from "./events.js";
import { createPanels } from "./panels.js";

// Template bootstrap for the graph UI refactor architecture.
export function createGraphUiApp() {
  const graphState = createGraphState();
  const layout = createLayoutEngine();
  const renderer = createRenderer();
  const interactions = createInteractions();
  const panels = createPanels();
  const events = createEventRouter({
    onFlush(batch) {
      // TODO: map event batch into incremental graph-state mutations.
      void batch;
    },
  });

  function start() {
    // TODO: initialize renderer, subscribe SSE, and run initial layout pass.
  }

  function stop() {
    events.clear();
    layout.disposeLayout();
    renderer.destroy();
  }

  return {
    start,
    stop,
    graphState,
    layout,
    renderer,
    interactions,
    panels,
    events,
  };
}
