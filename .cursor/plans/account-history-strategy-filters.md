# Account history strategy filters

**Goal:** Enable filtering of account history by all strategies in the strategy list, so users can slice transfers/trades by strategy from the UI.
**Scope:** In: backend query layer for account history, strategy list usage, and frontend filters/controls. Out: major redesign of account history UI beyond adding and wiring strategy filters.
**Status:** done

## Steps
1. Document current account history schema and how strategy information is stored/related.
2. Update backend endpoints (or add new ones) to support filtering account history by any strategy in the strategy list.
3. Implement frontend filter controls (dropdowns/checkboxes/etc.) that pull from the full strategy list and apply filters to history views.
4. Ensure filters work consistently on both desktop and mobile variants of the account history UI.

## Completion criteria
- [x] Backend supports filtering account history by strategy.
- [x] Frontend exposes strategy filters that cover the full strategy list.
- [x] Filters behave correctly on both desktop and mobile views.

## Blockers / decisions
- Confirm which strategies should be visible in filters (all vs a curated subset).

