# Pin: Upper / Lower Tail (2026-10-23)

```yaml
doc_id: PIN_UPPER_LOWER_TAIL
status: pinned_concept
not: implementation_spec
related: Lower Tail, Upper Tail, Local analysis backtests
resume: after additional backtests flesh lookback / MA / dead-zone details
```

One binary edge with a regime label, not two unrelated strategies.

- Meter: empirical **99¢-side win rate** vs **99%** break-even.
- **> 99%** → Upper Tail (expensive end; live: tape-triggered GTC at target, formerly called Taker Edge).
- **< 99%** → Lower Tail (cheap end; live: dual resting longshot bids, formerly called Maker Edge).
- Strength: signed distance from 99%. Lower Tail **≤ 98%** pins strength to max.
- Dead zone around 99%: watch only, no size from the meter.
- Smooth with MA / MA combo (details TBD).
- Side flips expected rare. BTC is the persistent Lower Tail case in ~9 months of backtests (volume). Main live use: dead-zone detection + strength-based sizing, not frequent flipping.

Product names are Upper Tail / Lower Tail (which end of the book). Execution differs: Upper Tail takes/triggers at the expensive rail; Lower Tail rests at the longshot rail.
