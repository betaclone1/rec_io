# Analyst memory — Index

Persistent context for the Analyst agent. **First and foremost for @analyst.** Read these on session start (after PM brain INDEX and 15_chat_summary_log). Be as technical and detailed as necessary. Do not modify project files outside this folder; analyst memory is analyst-writable.

## Purpose

Cursor does not retain chat context between sessions. The analyst memory docs are the Analyst's persistent context. Write backtest setups, parameter sweeps, strategy findings, monitor-tuning results, regime notes, and handoff context here so we do not lose continuity between chats.

## Doc map

| File | Purpose |
|------|--------|
| 00_db_and_data_flow | PostgreSQL schemas, key tables (users, live_data, historical_data, analytics), how scripts populate them, and how values (momentum, probability, symbol_close, monitor_confirmed, etc.) are calculated. Reference for queries and strategy work. |
| 01_backtest_patterns | Repeatable backtest setups, data windows, assumptions, and how to re-run them. Build over time toward automation. |
| 02_strategy_findings | Pattern discoveries, performance summaries, and recommendations from deep dives. |
| 03_regime_learning | Notes on regime detection, adaptation, and the initiative to have the system learn and adapt on its own. |
| 14_analyst_context | Catch-all for recent context, handoffs, open questions, and decisions that don't fit elsewhere. |

## Usage

- **On load / new chat:** After reading `.cursor/pm/brain/INDEX.md` and `15_chat_summary_log.md`, read this index and each doc above. Use them to resume work and to record new backtest patterns, findings, and regime/learning progress.
- **After material work:** Update the appropriate doc (e.g. add a backtest to 01_backtest_patterns, a finding to 02_strategy_findings). If it doesn't fit elsewhere, append to 14_analyst_context.

## Invariants

- No edits to repo files outside `.cursor/pm/brain/analyst/` unless explicitly asked or delegated (e.g. by PM or @db).
- Queries: read-only unless a specific write (e.g. saving backtest results to a table) is agreed and done via safe, documented path. Production: read-only unless change goes through normal deployment/checklist.
- Memory docs are for the Analyst's use first. Optimize for agent comprehension and continuity.
