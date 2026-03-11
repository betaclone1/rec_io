# Strategy findings

Pattern discoveries, performance summaries, and recommendations from deep dives. Use for continuity and to inform monitor tuning and regime work.

## Convention

- Date, scope (e.g. monitor X, strategy Y, period Z), finding in one or two sentences, and any caveat or follow-up.
- When adding a finding, append below.

## Findings

### BTC Hourly HTC losers vs winners (past 30 days, 2026-03-11)

- **Scope:** Production DB, symbol BTC, trade_strategy Hourly HTC, last 30 days; test_filter excluded; 9 losing trades, 255 winning.
- **At-entry:** In raw terms losers had momentum_percentile about -20 vs -12 for winners. Our strategies are directionally agnostic; magnitude matters more. In magnitude (abs): losers had stronger momentum at entry (|−20| ≈ 20 vs |−12| ≈ 12). So the hint is: when momentum was *strong* in either direction, we lost more often. Prob and volatility_percentile were similar; movement_percentile similar.
- **Price path:** In 3 of 9 losers price moved against us within 30m; in 4 of 9 by 60m. Mixed; not all losses were immediate run-against.
- **Testable hypothesis:** For directionally agnostic use: avoid or reduce size when *magnitude* of momentum at entry is very high (e.g. |momentum_percentile| above some threshold). Or: test whether a cap on max |momentum_percentile| at entry improves Hourly HTC PnL over the same period.
- **Caveat:** Only 9 losers; re-run with longer window for robustness.

---

*Last updated: 2026-03-11.*
