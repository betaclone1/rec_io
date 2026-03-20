# MTB / account balance & dashboard

**Goal:** Track and display Master Trading Bankroll (MTB) as a first-class concept, and surface it correctly in the account/dashboard UI.
**Scope:** In: DB schema/logic for MTB, backend APIs that expose account balance/MTB, and frontend dashboard presentation. Out: changes to core trading strategies that depend on MTB sizing (future work if needed).
**Status:** done (completed 2026-03-15)

## Steps
1. Document current bankroll/account balance schema and how it is shown in existing dashboards.
2. Design MTB representation in the DB (new column/table vs reuse) and how it interacts with existing bankroll fields.
3. Update backend logic to compute, store, and expose MTB via APIs.
4. Update frontend dashboards to display MTB where appropriate and make it clear when MTB vs other balances are shown.
5. Add basic tests/checks to ensure MTB stays in sync and is correctly reported.

## Completion criteria
- [x] MTB is represented clearly in the DB schema and referenced docs.
- [x] Backend services compute and expose MTB consistently.
- [x] Dashboards show MTB in the intended places with clear labeling.
- [x] Basic validation checks or tests exist for MTB correctness.

## Blockers / decisions
- Finalize how MTB should be defined (single value vs per-strategy variants) before implementation.

