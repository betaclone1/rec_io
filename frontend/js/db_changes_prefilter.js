/**
 * Fast path for /ws/db_changes: skip JSON.parse when the frame cannot match our streams.
 * High-volume streams (e.g. market_kalshi_15m) can flood the channel; parsing every frame
 * dominates CPU and can contribute to renderer OOM (Chrome "Aw, Snap" / error 5).
 *
 * Contract: payloads include "database": "<stream>" for db_change. Python json.dumps uses a
 * space after the colon; JSON.stringify is often compact — we match both.
 */
(function (g) {
  function rawMentionsDbStreamName(raw, stream) {
    if (typeof raw !== 'string' || stream === null || stream === undefined || stream === '') {
      return false;
    }
    const s = String(stream);
    return (
      raw.indexOf('"database":"' + s + '"') !== -1 ||
      raw.indexOf('"database": "' + s + '"') !== -1
    );
  }

  g.recDbChangeRawMentionsStream = function recDbChangeRawMentionsStream(raw, stream) {
    return rawMentionsDbStreamName(raw, stream);
  };
  g.recDbChangeRawMentionsAny = function recDbChangeRawMentionsAny(raw, streams) {
    if (typeof raw !== 'string' || !streams || !streams.length) return false;
    for (let i = 0; i < streams.length; i++) {
      if (rawMentionsDbStreamName(raw, streams[i])) return true;
    }
    return false;
  };
})(typeof window !== 'undefined' ? window : globalThis);
