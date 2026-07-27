# Historical cycle data product (warehouse → possible sale)

**Goal:** Evolve BTC 15m cycle capture/packaging from an internal backtest warehouse into an integrity-first, sellable historical data product—without changing the hot-table collection model more than necessary.

**Scope:** In: collection integrity, package format/versioning, compression choices, object-store + catalog, quality flags, legal/ToS gate. Out: building a storefront, multi-venue packages, non-BTC series (until BTC path is proven).

**Status:** draft  
**Priority:** normal (long-term; verify current packages after multi-hour soak first)

**Related:** Current capture/packager in `backend/core/cycle_hot_tables.py`, `backend/core/cycle_packager.py`; layout under `backend/data/historical_data/backtesting_data/KXBTC15M/…`. Design notes: [docs/HISTORICAL_CYCLE_DATA_PRODUCT.md](../../docs/HISTORICAL_CYCLE_DATA_PRODUCT.md).

## Near-term (before productization)

1. [ ] Soak BTC capture for several hours; verify sample `.tar.xz` packages (members, row counts, UTC alignment, OB eras).
2. [ ] Add closing OB snapshot at cycle end (terminal-era verify).
3. [ ] Add package `meta.json` integrity fields: schema_version, checksums, row counts, era list, gap/resync flags.
4. [ ] Confirm Kalshi / CFB redistribution terms before any external distribution design.

## Medium-term (warehouse hardening)

5. [ ] Immutable published artifacts (content-addressed or never-mutate; version bumps = new file).
6. [ ] Buyer-friendly encoding: Parquet (or Arrow) + zstd alongside or instead of CSV inside the archive; keep canonical logical schema.
7. [ ] Object store (S3/R2/Spaces) as system of record; local `backtesting_data/` as staging only.
8. [ ] Package catalog (DB or manifest): series, ticker, cycle window UTC, bytes, sha256, schema_version, quality flags.

## Later (commercial surface)

9. [ ] Product tiers (e.g. book-only vs book+spot+probs; delayed vs near-real-time) aligned with ToS.
10. [ ] Public docs: clocks (UTC), units, OB era replay contract, irreversible vs reconstructible fields.
11. [ ] Optional denser OB encoding for storage cost; recompress from canonical schema without rewriting history.

## Completion criteria

- [ ] Soak verification done and notes captured (pass/fail samples).
- [ ] Design doc remains the single source for “what we’d do differently for sale.”
- [ ] Legal/ToS gate resolved before any “sell” milestone is marked in progress.
- [ ] Catalog + object-store path specified enough to implement without re-litigating layout.

## Blockers / decisions

- **Legal:** Redistribution of Kalshi book / CFB index may be restricted; do not assume raw feed sale is allowed.
- **Format:** Keep CSV+xz acceptable for internal soak; Parquet+zstd is the likely external default.
- **Scope freeze:** BTC / KXBTC15M only until package quality is proven.
