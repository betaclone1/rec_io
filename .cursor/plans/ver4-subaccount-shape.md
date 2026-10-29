# VER4 Subaccount first move — sub/monitor shape

**Status:** in_progress (capital shape + AM UI landed; monitor bankroll binding next)  
**Branch:** `ver4/subaccount-system`  
**Parent:** `docs/VER4_DEVELOPMENT/SUBACCOUNT_ARCHITECTURE.md`

## Goal

Land the **sub / monitor capital shape** (not REBALANCE): trading vs non-trading / MTB membership, portfolio MTB Base Value, per-SA `% of Base`, bankroll policy tied to SA target, Subaccounts panel basics.

## Decisions (defaults for this slice)

| Question | Choice |
|----------|--------|
| Trading / MTB flag | `subaccounts_*.in_mtb BOOLEAN NOT NULL DEFAULT FALSE` — CASH/PRIMARY false; other existing rows seeded `TRUE` |
| Weight | `subaccounts_*.mtb_weight_pct DOUBLE PRECISION NULL` — percent points of MTB Base (e.g. `20` = 20%). `NULL` = unweighted / residual Unallocated inside MTB |
| Where MTB Base lives | `system_settings_*.mtb_base_value_cents INTEGER NULL` — portfolio-level user setting (cents). Distinct from per-SA `base_value` (rake HWM) |
| SA policy target $ | derived: `round(mtb_base_value_cents * mtb_weight_pct / 100)` when both set |
| Bankroll | Keep `dynamic_bankroll` (FALSE = static allotment). Later: seed allotment from SA policy target |
| REBALANCE | Out of scope |

## Steps

1. [x] Migration: `in_mtb`, `mtb_weight_pct` on all tenant live+paper `subaccounts_*`; seed CASH false / others true.
2. [x] Migration (same id): `mtb_base_value_cents` on all tenant `system_settings_*`.
3. [x] Schema ref + greenfield `system_settings` CREATE templates (+ cash-out correction `20261027_0700`).
4. [x] API: expose fields on `/api/subaccounts`; PATCH for `in_mtb` / `mtb_weight_pct`; GET/PATCH MTB Base on settings.
5. [x] Account Manager settings modal: show in_mtb + weight; create flow defaults `in_mtb=true` (desktop + mobile).
6. [x] Subaccounts panel first slice: list SAs, weights, Base, live MTB hint, derived target (desktop + mobile).
7. [x] Docs: update `SUBACCOUNT_ARCHITECTURE.md` §7 closed decisions.
8. [ ] Next: pin monitor bankroll / allotment to SA policy target; monitor membership chrome.

## Done when

Local migration applied; APIs return new fields; Account Manager can edit weight/in_mtb; Subaccounts panel shows Base + weighted SAs (even if chart is minimal).
