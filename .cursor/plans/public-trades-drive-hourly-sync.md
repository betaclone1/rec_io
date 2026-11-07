# Public trades + market results → Google Drive hourly sync

**Goal:** Keep a full Drive archive of Kalshi public-trades + market-results CSVs, broken out by asset and month, updated hourly from prod as a background process with no impact on the live trading pipeline.
**Scope:** New isolated supervisor worker + packaging/upload path under existing Drive BACKTESTING_DATA layout; reuse catchup/pull scripts; no changes to market_watchdog, monitors, or Redis hot path.
**Status:** done

## Layout (Drive)

Under `DATA/HISTORICAL_DATA/BACKTESTING_DATA` (same OAuth / folder id as cycle packages):

```
{SERIES}/{YYYY}/{YYYY_MM_MON}/{SERIES}_public_trades_{YYYY-MM}_et.tar.xz
```

Archive members: day `*_public_trades_*_et.csv`, month `*_market_results_*_et.csv`, manifest JSON.

## Isolation rules

- Separate supervisord program (`public_trades_drive_sync`); not inlined into market_watchdog / cycle_packager logic beyond shared Drive creds env pattern.
- No Redis, no tenant/monitor DML, no order placement.
- Kalshi public REST only (existing pull scripts), low worker count.
- Writes only under `backend/data/historical_data/kalshi_public_trades/` and month archives under `backtesting_data/{SERIES}/…`.

## Steps

1. Add `backend/public_trades_drive_sync.py` hourly loop (`--once` for manual).
2. Each wake: refresh recent day CSVs (force today/yesterday), refresh market-result cache/month exports, rebuild dirty month `.tar.xz`, upload changed archives via `upload-backtesting-data.js`.
3. Wire supervisord + Drive OAuth env (mirror cycle_packager pattern); feature-gated autostart.
4. Document one-time historical backfill + hourly behavior in `docs/LOWER_TAIL_STRATEGY.md` / gdrive README.
5. Local dry-run of `--once --dry-run-upload`.

## Completion criteria

- [x] Worker exists and can run `--once` without touching live services
- [x] Month archives land under `{SERIES}/{YYYY}/{YYYY_MM_MON}/`
- [x] Supervisord generator registers the program
- [x] Docs describe seed backfill vs hourly maintain
- [x] Explicit note: deploy to prod still requires user instruction

## Blockers / decisions

- Full historical seed is a one-time (or slow backfill) job; hourly maintains a short lookback + current/previous month re-package.
- Drive target: reuse BACKTESTING_DATA (not a new top-level folder) unless owner prefers a sibling.
