# KXETH15M YTD 2026 — exact-cent cum≥2500 monthly results

**Model:** first exact `$0.01` touch (YES or NO), require cumulative tape volume on that side at `$0.01` ≥ **2500** contracts, hold to settlement. No TTC filter.  
**Size:** 2500 contracts · **Start bankroll:** $10,000  
**Span (ET):** 2026-01-01 → 2026-10-18 (October partial)  
**Script:** `scripts/backtest/kxbtc15m_exact_cent_cum_size_span.py --series KXETH15M`  
**Source:** `backend/data/historical_data/kalshi_public_trades/KXETH15M_exact_cent_cum2500_limit0.01_2026-01-01_2026-10-18_et_by_month.csv`  
**Compare:** BTC counterpart `docs/BACKTEST_KXBTC15M_YTD_2026_EXACT_CENT_CUM2500.md` (same params).

## Headline

```
Scored trades                 12,908
Wins / losses            107 / 12,801
Win rate                       0.83%
PnL                       -$55,200
Ending equity             -$45,200
Lowest bankroll           -$48,100   (2026-10-17; peak→trough DD $58,100)
short_tape skipped            13,752
unknown_result                     0
```

## Monthly breakdown

**Low bankroll** = lowest running YTD equity during that month (start bankroll $10k).  
**Isolated eq** = that month alone starting from $10k (not the running path).  
**ADV** = average daily volume: mean over days with scored trades of (sum of `vol_at_L` that day).

```
Month              Scored      W      L    WR%         PnL  Low bankroll  Isolated eq      Outlay          ADV
---------------  --------  -----  -----  -----  ----------  ------------  ------------  ----------  -----------
2026-01                19      0     19   0.00       -$475        $9,525        $9,525        $475       13,660
2026-02               435      2    433   0.46     -$5,875        $3,650        $4,125     $10,875       60,856
2026-03               802      6    796   0.75     -$5,050       -$4,625        $4,950     $20,050      105,369
2026-04               574      3    571   0.52     -$6,850       -$9,125        $3,150     $14,350       73,071
2026-05               326      6    320   1.84     +$6,850       -$9,900       $16,850      $8,150       38,068
2026-06             1,352      6  1,346   0.44    -$18,800      -$21,100       -$8,800     $33,800      216,802
2026-07             2,444     23  2,421   0.94     -$3,600      -$36,225        $6,400     $61,100      483,017
2026-08             2,618     20  2,598   0.76    -$15,450      -$39,250       -$5,450     $65,450      539,336
2026-09             2,686     27  2,659   1.01       +$350      -$41,000       $10,350     $67,150      807,459
2026-10 (1–18)      1,652     14  1,638   0.85     -$6,300      -$48,100        $3,700     $41,300    1,708,762
---------------  --------  -----  -----  -----  ----------  ------------  ------------  ----------  -----------
Total              12,908    107 12,801   0.83    -$55,200      -$48,100            —           —           —
```

## Days by win count (from 2026-05-01)

Calendar ET days with scored trades. May 1–Oct 18: 171 active days; **103** zero-win (60.2%).

```
Month            0 wins   1 win   2 wins   3 wins   4+ wins   Active   0-win %
---------------  ------  ------  -------  -------  --------  -------  -------
2026-05              25       6        0        0         0       31    80.6%
2026-06              24       6        0        0         0       30    80.0%
2026-07              17       7        6        0         1       31    54.8%
2026-08              17       9        4        1         0       31    54.8%
2026-09              12      10        7        1         0       30    40.0%
2026-10 (1–18)        8       7        2        1         0       18    44.4%
---------------  ------  ------  -------  -------  --------  -------  -------
Total               103      45       19        3         1      171    60.2%
```

### Streaks longer than 24 hours (from 2026-05-01)

Zero-win calendar runs of ≥ 2 days starting on/after 2026-05-01.  
**Hours** = time from last win before the run to first win after (longest first).

```
Hours   Zero-win dates (ET)
-----   -------------------------
305.5   2026-05-24 → 2026-06-04
245.0   2026-06-12 → 2026-06-20
181.3   2026-05-10 → 2026-05-16
171.9   2026-05-01 → 2026-05-03
169.2   2026-06-23 → 2026-06-29
166.5   2026-07-06 → 2026-07-11
165.8   2026-08-17 → 2026-08-22
134.3   2026-10-13 → 2026-10-16
110.0   2026-05-05 → 2026-05-08
103.5   2026-06-08 → 2026-06-10
102.1   2026-09-17 → 2026-09-19
 92.0   2026-09-23 → 2026-09-25
 91.7   2026-09-29 → 2026-10-01
 89.5   2026-08-06 → 2026-08-08
 86.3   2026-07-02 → 2026-07-04
 80.5   2026-05-18 → 2026-05-19
 79.0   2026-08-24 → 2026-08-26
 73.5   2026-07-13 → 2026-07-14
 59.0   2026-10-07 → 2026-10-08
```

## Other artifacts

Same directory / stem `KXETH15M_exact_cent_cum2500_limit0.01_2026-01-01_2026-10-18`:

| Artifact | Suffix |
|----------|--------|
| Totals | `_et_totals.csv` |
| By week | `_et_by_week.csv` |
| Events | `_et.csv` |
