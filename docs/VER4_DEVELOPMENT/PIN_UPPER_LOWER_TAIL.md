# Pin: Upper / Lower Tail (2026-10-23)

```yaml
doc_id: PIN_UPPER_LOWER_TAIL
status: pinned_concept
not: implementation_spec
related: Maker Edge, Taker Edge, Local analysis backtests
resume: after additional backtests flesh lookback / MA / dead-zone details
```

One binary edge with a regime label, not two unrelated strategies.

- Meter: empirical **99¢-side win rate** vs **99%** break-even.
- **> 99%** → Upper Tail (expensive end; live shape today: Taker Edge).
- **< 99%** → Lower Tail (cheap end; live shape today: Maker Edge).
- Strength: signed distance from 99%. Lower Tail **≤ 98%** pins strength to max.
- Dead zone around 99%: watch only, no size from the meter.
- Smooth with MA / MA combo (details TBD).
- Side flips expected rare. BTC is the persistent Lower Tail case in ~9 months of backtests (volume). Main live use: dead-zone detection + strength-based sizing, not frequent flipping.

“Maker” / “Taker” name execution. Upper / Lower Tail name which end of the book the thesis is harvesting.
