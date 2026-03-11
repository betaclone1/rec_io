# Analyst context (catch-all)

Recent context, handoffs, open questions, and decisions that don't fit in 01–03. Append below so the next session has continuity.

## Recent context / handoff

**2026-03-11 — Backtest methodology (first step).** We are iterating on backtests and presentation: interpret conversational asks (e.g. "optimal probability window" = min and max; "last month" = prior calendar month). Record patterns in 01_backtest_patterns. Window backtests: grid (min, max) with prob BETWEEN min AND max; find best by PnL.

**2026-03-11 — Analytics department and @analyst created.** New department headed by @analyst; same context retention depth as PM. Scope: strategy performance, deep dives, analytics/historical/live data systems, market news (BTC, ETH, crypto, financial), backtests, monitor tuning, simulated/hypothetical PnL, backtest pattern retention and automation, regime learning initiative. Works hand-in-hand with @db for queries on local and production. Analyst memory: `.cursor/pm/brain/analyst/` (INDEX_ANALYST, 00_db_and_data_flow, 01_backtest_patterns, 02_strategy_findings, 03_regime_learning, 14_analyst_context). First step when invoked: read PM brain INDEX, 15_chat_summary_log, then analyst INDEX_ANALYST and listed docs.

**Dev vs production:** Dev = this machine + local DB (synced on release; monitors not run for real strategy). Production = server with live monitors 24/7 and calibrated strategies. For trade/strategy analysis (real, paper, simulated), use **production DB** unless explicitly asked for dev-only. Dev DB is for schema checks, script testing, dev experiments.

---

*Last updated: 2026-03-11.*
