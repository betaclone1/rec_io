/**
 * Shared websocket coordinator for same-origin realtime channels.
 * Ensures one socket per URL and fanout subscriptions for page modules.
 */
(function () {
  const socketsByUrl = new Map();

  function safeCall(fn, arg) {
    try {
      fn(arg);
    } catch (e) {}
  }

  function ensureSocket(url) {
    let entry = socketsByUrl.get(url);
    if (entry) return entry;
    entry = {
      url: url,
      ws: null,
      reconnectTimer: null,
      reconnectMs: 2500,
      subscribers: new Set(),
    };
    socketsByUrl.set(url, entry);
    connect(entry);
    return entry;
  }

  function connect(entry) {
    if (!entry || typeof WebSocket === 'undefined') return;
    if (
      entry.ws &&
      (entry.ws.readyState === WebSocket.OPEN || entry.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    try {
      if (entry.ws) entry.ws.close();
    } catch (e) {}
    entry.ws = null;
    let ws;
    try {
      ws = new WebSocket(entry.url);
    } catch (e) {
      scheduleReconnect(entry);
      return;
    }
    entry.ws = ws;
    ws.onmessage = function (event) {
      entry.subscribers.forEach(function (sub) {
        safeCall(sub.onMessage, event);
      });
    };
    ws.onopen = function (event) {
      if (entry.reconnectTimer) {
        clearTimeout(entry.reconnectTimer);
        entry.reconnectTimer = null;
      }
      entry.subscribers.forEach(function (sub) {
        if (typeof sub.onOpen === 'function') safeCall(sub.onOpen, event);
      });
    };
    ws.onclose = function (event) {
      entry.ws = null;
      entry.subscribers.forEach(function (sub) {
        if (typeof sub.onClose === 'function') safeCall(sub.onClose, event);
      });
      if (entry.subscribers.size > 0) scheduleReconnect(entry);
    };
    ws.onerror = function () {
      try {
        ws.close();
      } catch (e) {}
    };
  }

  function scheduleReconnect(entry) {
    if (!entry || entry.reconnectTimer || entry.subscribers.size === 0) return;
    entry.reconnectTimer = setTimeout(function () {
      entry.reconnectTimer = null;
      connect(entry);
    }, entry.reconnectMs);
  }

  function unsubscribe(entry, sub) {
    if (!entry) return;
    entry.subscribers.delete(sub);
    if (entry.subscribers.size > 0) return;
    if (entry.reconnectTimer) {
      clearTimeout(entry.reconnectTimer);
      entry.reconnectTimer = null;
    }
    try {
      if (entry.ws) entry.ws.close();
    } catch (e) {}
    entry.ws = null;
    socketsByUrl.delete(entry.url);
  }

  window.recRealtimeWsCoordinator = {
    subscribe: function (url, handlers) {
      if (!url) return function () {};
      const entry = ensureSocket(String(url));
      const sub = {
        onMessage: handlers && handlers.onMessage,
        onOpen: handlers && handlers.onOpen,
        onClose: handlers && handlers.onClose,
      };
      entry.subscribers.add(sub);
      return function () {
        unsubscribe(entry, sub);
      };
    },
  };
})();
