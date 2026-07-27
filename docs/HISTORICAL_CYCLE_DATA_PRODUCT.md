# Historical cycle data product — collection, compression, storage

Internal backtest packages (BTC 15m cycle `.tar.xz` under `backend/data/historical_data/backtesting_data/`) are a solid skeleton for a longer-term **warehousable / possibly commercial** historical dataset. This note records what we would do differently at collection, compression, and storage if the goal included **selling** that data.

**Task tracking:** [.cursor/plans/historical-cycle-data-product.md](../.cursor/plans/historical-cycle-data-product.md)

**Current ballpark:** ~1.5–2.5 MB xz per 15m symbol cycle (~40–87 GB/year/symbol depending on encoding and book activity). OB dominates; strike + price/metrics rings are ~15 KB combined.

---

## What already fits a product

- **Per-ticker sealed cycles** — self-contained packages, not an unbounded live table dump.
- **UTC-aligned** price ring, metrics ring, and irreversible strike fields.
- **Hot PG → package → drop** after verify (hot path stays lean; warehouse is the durable form).
- **Piecewise OB eras** at resyncs (honest completeness model).

Do not replace that collection model lightly. Productization is mostly **integrity, format, catalog, and legal**.

---

## Legal / ToS (gate)

Before investing in a commercial warehouse or external distribution:

- Confirm what Kalshi (and CFB / index) terms allow: raw book, delayed book, derived features only, etc.
- That decision drives tiers (what you sell) more than compression ratios.

No “sell” milestone should start until this is resolved.

---

## Collection

| Practice | Why |
|----------|-----|
| Seal each cycle as an artifact with **integrity metadata** | Buyers (and future you) need row counts, first/last UTC, checksums per member, schema version |
| Record **OB era boundaries** (`snapshot_seq` list) and gap/resync flags | Completeness is “complete within eras,” not a fake continuous book |
| Add a **closing OB snapshot** at cycle end | Makes the last era verifiable without assuming the stream ended cleanly |
| One write path → package | Avoid dual live + archive systems that drift |
| Keep irreversible fields explicit | Strike probs / fair (and profile-tied metrics) cannot be reconstructed later |

---

## Compression / package format

| Practice | Why |
|----------|-----|
| **CSV + xz** for internal soak | Fine for ops and early verification |
| For sale: **Parquet (or Arrow IPC) + zstd** + small `meta.json` | Typed columns; loads cleanly in Pandas/Spark |
| Stable **content-addressed / immutable** names | Never mutate a published package; version bump = new artifact |
| Optional denser OB encoding later | ~1.5–2× storage win possible; keep a **canonical logical schema** so you can recompress without rewriting history |

Rings and strike will never dominate size; optimize the book path if warehouse cost matters.

---

## Storage

| Practice | Why |
|----------|-----|
| **Object store** (S3 / R2 / Spaces) as system of record | Local `backtesting_data/` is staging, not the product catalog |
| Lifecycle tiers (hot → cool → archive) | Year-scale BTC (and later multi-symbol) cost control |
| Catalog (DB or manifest): series, ticker, cycle window UTC, bytes, sha256, schema_version, quality flags | Billing, sampling, re-delivery, QA |
| Partition `series / year / YYYY_MM_MON` (e.g. `2026_07_JUL`; add **day** if volume grows) | Matches current layout; UTC inside package, Eastern only as derived labels |

---

## Product surface (later)

- Sell **self-contained cycle packages** with docs: clocks (UTC), units, how to replay OB eras, irreversible vs reconstructible.
- **Tiers** aligned with ToS: e.g. book-only vs book+spot+probs; delayed vs near-real-time.
- Public schema version changelog so buyers can trust multi-year archives.

---

## Explicit non-goals (for now)

- Storefront / payments / customer accounts.
- Multi-series packaging before BTC soak quality is proven.
- Replacing hot capture with a different live pipeline solely for “product” aesthetics.

---

## Revision

| Date | Note |
|------|------|
| 2026-07-26 | Initial write-up from cycle-package design discussion; plan filed under `.cursor/plans/historical-cycle-data-product.md`. |
