# Public trades Drive sync — low-impact hourly

**Goal:** Keep Kalshi public-trades + market-results + LT/UT cycle/rolling scores fresh without pinning CPU on full-day re-pulls / month packaging every hour.
**Status:** done (2026-11-19) — incremental default wake; archive opt-in
**Related:** `.cursor/plans/public-trades-drive-hourly-sync.md` (original always-on full catchup; superseded for *default* wake cost)

## Decision (pinned)

**Default hourly wake = incremental only:**
- Pull tickers in `PUBLIC_TRADES_DRIVE_SYNC_HOURS_BACK` (default 2h) and merge into day CSVs
- Bulk market-result refresh (no month CSV export)
- Score lookback days touched by that window + refresh rolling rates
- **No** month `tar.xz` / Drive upload

**Archive / Drive package** = opt-in (`PUBLIC_TRADES_DRIVE_SYNC_ARCHIVE=1` or `--archive` / `--backfill-local-months`).

**Idle floor:** `PUBLIC_TRADES_DRIVE_SYNC_MIN_IDLE_SEC` (default 300) so overruns cannot tight-loop.

## Completion criteria

- [x] Default `run_once` is incremental (hours-back merge + score)
- [x] Archive path remains available but off by default
- [x] Entrypoint sleep uses min idle floor
- [x] Docs in `docs/LOWER_TAIL_STRATEGY.md` reflect incremental vs archive
