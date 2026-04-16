/**
 * Keyset-paged GET /trades: fetches page_size rows per request until has_more is false,
 * then returns one merged array (slim trade rows from read_api).
 *
 * @param {string} firstPageUrl - Absolute URL; query may include min_date, max_date, status; must not include before_id for the first request (caller resets paging by passing a fresh URL).
 * @param {{ cache?: RequestCache }} [fetchOpts] - passed to fetch()
 * @param {(loadedCount: number, hasMore: boolean) => void} [onProgress] - optional; called after each page
 * @returns {Promise<object[]>}
 */
(function (global) {
  'use strict';

  var PAGE_SIZE = 500;

  async function recFetchTradesMerged(firstPageUrl, fetchOpts, onProgress) {
    var opts = fetchOpts || { cache: 'no-store' };
    var fetchImpl = typeof opts.customFetch === 'function' ? opts.customFetch : null;
    var passOpts = {};
    for (var k in opts) {
      if (Object.prototype.hasOwnProperty.call(opts, k) && k !== 'customFetch') {
        passOpts[k] = opts[k];
      }
    }
    var merged = [];
    var beforeId = null;
    var guard;
    for (guard = 0; guard < 10000; guard++) {
      var u =
        typeof firstPageUrl === 'string' && /^https?:\/\//i.test(firstPageUrl)
          ? new URL(firstPageUrl)
          : new URL(firstPageUrl, window.location.origin);
      u.searchParams.set('page_size', String(PAGE_SIZE));
      if (beforeId != null) {
        u.searchParams.set('before_id', String(beforeId));
      } else {
        u.searchParams.delete('before_id');
      }
      var urlStr = u.toString();
      var res = fetchImpl
        ? await fetchImpl(urlStr, passOpts)
        : await fetch(urlStr, passOpts);
      var raw = await res.text();
      if (!res.ok) {
        var msg = 'HTTP ' + res.status;
        try {
          var err = JSON.parse(raw);
          if (err && typeof err.detail === 'string') msg = err.detail;
        } catch (_) {}
        throw new Error(msg);
      }
      var data;
      try {
        data = JSON.parse(raw);
      } catch (e) {
        throw new Error('Invalid JSON from /trades');
      }
      var list;
      var hasMore = false;
      var nextBefore = null;
      if (Array.isArray(data)) {
        list = data;
      } else if (data && Array.isArray(data.trades)) {
        list = data.trades;
        hasMore = !!data.has_more;
        nextBefore = data.next_before_id != null ? Number(data.next_before_id) : null;
      } else {
        throw new Error('Invalid /trades payload');
      }
      for (var i = 0; i < list.length; i++) merged.push(list[i]);
      if (typeof onProgress === 'function') {
        onProgress(merged.length, hasMore);
      }
      if (!hasMore || nextBefore == null) break;
      beforeId = nextBefore;
    }
    return merged;
  }

  global.recFetchTradesMerged = recFetchTradesMerged;
})(typeof globalThis !== 'undefined' ? globalThis : window);
