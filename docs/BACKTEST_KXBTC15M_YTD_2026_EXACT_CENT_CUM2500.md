# KXBTC15M YTD 2026 — exact-cent cum≥2500 monthly results

**Model:** first exact `$0.01` touch (YES or NO), require cumulative tape volume on that side at `$0.01` ≥ **2500** contracts, hold to settlement. No TTC filter.  
**Size:** 2500 contracts · **Start bankroll:** $10,000  
**Span (ET):** 2026-01-01 → 2026-10-17 (October partial)  
**Script:** `scripts/backtest/kxbtc15m_exact_cent_cum_size_span.py`  
**Source:** `backend/data/historical_data/kalshi_public_trades/KXBTC15M_exact_cent_cum2500_limit0.01_2026-01-01_2026-10-17_et_by_month.csv`  
**Related:** `docs/MAKER_EDGE_STRATEGY.md` (tape-oracle model; live Maker Edge is dual-rest, not identical).

## Headline

```
Scored trades                 24,358
Wins / losses            329 / 24,029
Win rate                       1.35%
PnL                      +$213,550
Ending equity             $223,550
Lowest bankroll           -$32,950   (2026-04-10; peak→trough DD $46,950)
```

## Monthly breakdown

**Low bankroll** = lowest running YTD equity during that month (start bankroll $10k).  
**Isolated eq** = that month alone starting from $10k (not the running path).  
**ADV** = average daily volume: mean over days with scored trades of (sum of `vol_at_L` that day). `vol_at_L` = full-cycle cum contracts traded at $0.01 on the chosen side (scored markets only).

```
Month              Scored      W      L    WR%         PnL  Low bankroll  Isolated eq      Outlay          ADV
---------------  --------  -----  -----  -----  ----------  ------------  ------------  ----------  -----------
2026-01               550      4    546   0.73     -$3,750        $5,700        $6,250     $13,750       87,432
2026-02             2,303     17  2,286   0.74    -$15,075      -$23,900       -$5,075     $57,575    1,029,033
2026-03             2,802     22  2,780   0.79    -$15,050      -$25,525       -$5,050     $70,050    1,729,087
2026-04             2,710     30  2,680   1.11     +$7,250      -$32,950       $17,250     $67,750    1,270,305
2026-05             2,892     39  2,853   1.35    +$25,200      -$18,700       $35,200     $72,300    1,778,658
2026-06             2,825     38  2,787   1.35    +$24,375        $5,550       $34,375     $70,625    4,627,723
2026-07             2,918     44  2,874   1.51    +$37,050       $31,700       $47,050     $72,950    7,925,453
2026-08             2,932     55  2,877   1.88    +$64,200       $69,725       $74,200     $73,300   10,308,579
2026-09             2,842     52  2,790   1.83    +$58,950      $129,500       $68,950     $71,050   16,531,882
2026-10 (1–17)      1,584     28  1,556   1.77    +$30,400      $190,325       $40,400     $39,600   22,353,471
---------------  --------  -----  -----  -----  ----------  ------------  ------------  ----------  -----------
Total              24,358    329 24,029   1.35   +$213,550      -$32,950            —           —           —
```

## Days by win count (from 2026-05-01)

Calendar ET days with scored trades, bucketed by number of wins that day. May 1–Oct 17: 170 active days; **32** zero-win (18.8%).

```
Month            0 wins   1 win   2 wins   3 wins   4+ wins   Active   0-win %
---------------  ------  ------  -------  -------  --------  -------  -------
2026-05               5      16        8        1         1       31    16.1%
2026-06               8      12        6        3         1       30    26.7%
2026-07               7       8       13        2         1       31    22.6%
2026-08               4       9       12        3         3       31    12.9%
2026-09               2      12        8        8         0       30     6.7%
2026-10 (1–17)        6       1        6        2         2       17    35.3%
---------------  ------  ------  -------  -------  --------  -------  -------
Total                32      58       53       19         8      170    18.8%
```

### Streaks longer than 24 hours (from 2026-05-01)

Zero-win calendar runs of ≥ 2 days starting on/after 2026-05-01.  
**Hours** = time from last win before the run to first win after (longest first).

```
Hours   Zero-win dates (ET)
-----   -------------------------
 97.8   2026-10-07 → 2026-10-09
 66.4   2026-06-19 → 2026-06-20
 65.7   2026-05-25 → 2026-05-26
 61.2   2026-08-20 → 2026-08-21
 57.5   2026-05-15 → 2026-05-16
```

## Other artifacts

Same directory / stem `KXBTC15M_exact_cent_cum2500_limit0.01_2026-01-01_2026-10-17`:

| Artifact | Suffix |
|----------|--------|
| Totals | `_et_totals.csv` |
| By week | `_et_by_week.csv` |
| Events | `_et.csv` |
