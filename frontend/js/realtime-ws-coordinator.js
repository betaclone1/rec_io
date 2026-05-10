/**
 * Shared websocket coordinator for same-origin realtime channels.
 * Ensures one socket per URL and fanout subscriptions for page modules.
 *
 * - Parses each frame at most once (fanout shares `recWsParsed`).
 * - Optional `onlyDbStreams` + `includeLiveSymbolSpot`: skip JSON.parse entirely when no
 *   subscriber cares about that frame (high-volume /ws/db_changes firehose → less CPU/OOM risk).
 */
(function () {
  const socketsByUrl = new Map();

  function safeCall(fn, arg) {
    try {
      fn(arg);
    } catch (e) {}
  }

  function rawMentionsLiveSymbolSpot(raw) {
    if (typeof raw !== 'string') return false;
    return (
      raw.indexOf('"type":"live_symbol_spot"') !== -1 ||
      raw.indexOf('"type": "live_symbol_spot"') !== -1
    );
  }

  function subscriberWantsRawMessage(sub, raw) {
    if (!sub || typeof sub.onMessage !== 'function') return false;
    if (typeof raw !== 'string') return true;
    const streams = sub.onlyDbStreams;
    const hasStreamFilter = streams && streams.length > 0;
    if (!hasStreamFilter && !sub.includeLiveSymbolSpot) return true;
    if (sub.includeLiveSymbolSpot && rawMentionsLiveSymbolSpot(raw)) return true;
    const win = typeof window !== 'undefined' ? window : globalThis;
    if (
      hasStreamFilter &&
      typeof win.recDbChangeRawMentionsAny === 'function' &&
      win.recDbChangeRawMentionsAny(raw, streams)
    ) {
      return true;
    }
    return false;
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
      const raw = event && event.data;
      let anyInterested = false;
      entry.subscribers.forEach(function (sub) {
        if (subscriberWantsRawMessage(sub, raw)) anyInterested = true;
      });
      if (!anyInterested) return;

      let parsed = null;
      if (typeof raw === 'string') {
        try {
          parsed = JSON.parse(raw);
        } catch (e) {
          parsed = null;
        }
      }

      const fanout = { data: raw, recWsParsed: parsed };
      entry.subscribers.forEach(function (sub) {
        if (!subscriberWantsRawMessage(sub, raw)) return;
        safeCall(sub.onMessage, fanout);
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
        onlyDbStreams: handlers && handlers.onlyDbStreams,
        includeLiveSymbolSpot: !!(handlers && handlers.includeLiveSymbolSpot),
      };
      entry.subscribers.add(sub);
      return function () {
        unsubscribe(entry, sub);
      };
    },
  };

  /** Use instead of JSON.parse(event.data) for coordinator-delivered frames (single shared parse). */
  window.recRealtimeWsJson = function (event) {
    if (event && Object.prototype.hasOwnProperty.call(event, 'recWsParsed')) {
      return event.recWsParsed;
    }
    if (!event || typeof event.data !== 'string') return null;
    try {
      return JSON.parse(event.data);
    } catch (e) {
      return null;
    }
  };
})();
