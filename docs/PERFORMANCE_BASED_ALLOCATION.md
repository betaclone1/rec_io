# Performance-Based Allocation (PBA)

## Overview
Performance-Based Allocation automatically scales a monitor’s bankroll exposure using historical risk/return data while respecting liquidity limits. The goal is to reward consistently profitable weekly cycles and throttle weak ones without manual intervention.

This document is intended for external review and describes the current implementation as of November 2025.

---

## Data Pipeline
1. **Per-Cycle Metrics:**  
   - `users.monitor_cycle_performance_<user>_<monitor>` stores 168 hourly buckets (Sun 1 am → Sat 12 am).  
   - Each bucket contains:
     - `performance_modifier` (numeric, 0.00–2.00)  
     - `max_pct_exposure` (numeric)  
     - Aggregate trade counts, win rate, and exposure statistics over a rolling 12‑week window.

2. **Current Cycle Snapshot (`monitor_list` table):**  
   These columns are maintained per monitor:
   - `current_contract`  
   - `current_weekly_cycle` (1–168)  
   - `current_performance_modifier`  
   - `current_max_pct_exposure`  
   - `performance_based_allocation` (boolean flag)  
   - `multiplier`, `position_size`, `total_position`, etc.

3. **Services Involved:**
   - `auto_entry_supervisor` (AES) – detects the active cycle, updates the `current_*` fields, and applies modifiers if PBA is enabled.
   - `monitor_manager` – authoritative recalculation of `total_position` whenever position settings change.
   - `main` service – writes bankroll reallocations and forwards monitor updates to `monitor_manager`.
   - Frontend (dashboard & trade monitors) – reflect multiplier/total changes in real time.

---

## Runtime Flow
1. **Cycle Detection:**  
   AES parses the monitoring feed, derives `current_weekly_cycle`, then looks up `performance_modifier` and `max_pct_exposure` from the cycle table. It writes these into `users.monitor_list_*`.

2. **Modifier Application:**  
   If `performance_based_allocation = TRUE`, AES calls `POST /api/update_monitor_position` with the fetched modifier.  
   ⇒ Monitor manager updates `multiplier` and recomputes `total_position`.

3. **Exposure Cap:**  
   When `position_type = 'percent'`, monitor_manager uses:  
   `effective_pct = min(position_size_pct * multiplier, current_max_pct_exposure)`  
   `total_position = max(1, round(bankroll_allotment_total * effective_pct))`  
   Contracts mode (`position_type = 'contracts'`) is unchanged.

4. **Loss Prevention Override:**  
   If a monitor’s `loss_prevention = 'one_contract'`, AES always submits trades with a single contract, independent of the multiplier or PBA.

5. **Broadcast & UI Sync:**  
   The recalculated `total_position` and active multiplier broadcast via `/api/broadcast_monitor_total_position`.  
   - Dashboard allocation badge updates to LP / 1c / ½x / 1x / 1.5x / 2x.  
   - Desktop and mobile trade monitors highlight the corresponding multiplier button and show the updated total contracts.

---

## Operational Behavior
- **Scaling Up:** High win-rate hours gain multipliers up to 2.00 but are capped if the cycle historically spawned multiple legs.
- **Scaling Down:** Weak cycles (modifier = 0.00 or 0.50) are throttled toward minimum exposure, mitigating drawdowns.
- **Manual Overrides:** Users can disable PBA at any time; manual multiplier clicks continue to work and are subject to the same max-exposure cap.
- **Regime Changes:** Modifiers recompute daily (rolling 12-week window), so improvements in performance eventually re-escalate allocations.

---

## Edge Cases & Safeguards
| Scenario | Result |
| --- | --- |
| `loss_prevention = 'one_contract'` | AES enforces 1 contract per trade regardless of multiplier |
| `current_max_pct_exposure` missing/0 | Defaults to base calculation, minimum 1 contract |
| `position_type = 'contracts'` | Capped at `position_size * multiplier` (no pct cap) |
| PBA disabled mid-cycle | Multiplier remains whatever the user/AES last set; no automatic adjustments |
| WebSocket disconnect | Frontend refetches `/api/monitor/{id}` to restore multiplier state |

---

## Testing Notes
- Integration tested with monitors 10002/10009 to ensure:
  - AES writes `current_*` fields correctly each hour.  
  - `performance_based_allocation` toggles multiplier updates.  
  - max exposure caps prevent over-allocation when multiplier × base percentage exceeds historical legs.
- UI verified on desktop & mobile for badge and button synchronization.

---

## Future Enhancements
- Optional UI exposure chart to visualize cap vs. requested allocation.
- Alerting when cycles become capped frequently, signaling potential liquidity constraints.
- Granular caps per contract mode (e.g., separate caps for yes/no legs).

---

*Document version: 2025-11-09*.


