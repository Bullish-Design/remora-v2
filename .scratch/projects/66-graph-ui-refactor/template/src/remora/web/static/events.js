// Template SSE event batching + reconciliation entrypoint.

export function createEventRouter({ flushIntervalMs = 75, onFlush } = {}) {
  let timerId = null;
  const queue = [];

  function scheduleFlush() {
    if (timerId != null) return;
    timerId = setTimeout(() => {
      timerId = null;
      if (queue.length === 0) return;

      const batch = queue.splice(0, queue.length);
      if (typeof onFlush === "function") {
        onFlush(batch);
      }
    }, flushIntervalMs);
  }

  function push(eventType, payload) {
    queue.push({ eventType, payload, receivedAt: Date.now() });
    scheduleFlush();
  }

  function clear() {
    queue.length = 0;
    if (timerId != null) {
      clearTimeout(timerId);
      timerId = null;
    }
  }

  return {
    push,
    clear,
  };
}
