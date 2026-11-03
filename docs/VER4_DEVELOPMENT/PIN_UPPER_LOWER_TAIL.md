# Pin: Upper / Lower Tail (2026-10-23; superseded operating model 2026-10-31)

```yaml
doc_id: PIN_UPPER_LOWER_TAIL
status: pinned_concept_historical
superseded_operating_model: CORE_TAIL_BIAS_STRATEGY.md
not: implementation_spec
related: Lower Tail, Upper Tail, Local analysis backtests
resume: see CORE_TAIL_BIAS_STRATEGY.md for live probe → bias → sized arms
```

**v4 CORE operating model:** [`CORE_TAIL_BIAS_STRATEGY.md`](CORE_TAIL_BIAS_STRATEGY.md) — dual live UT/LT probes per asset, W/L-only meter, rolling MAs, WR goals (~99% / ~1%), strength-gated sized trading. **That file is authoritative for agents.**

---

## Original pin (2026-10-23) — economic intuition

One binary edge with a regime label, not two unrelated strategies.

- Meter: empirical **99¢-side win rate** vs **99%** break-even.
- **> 99%** → Upper Tail (expensive end; live: trigger GTC at target, formerly Taker Edge).
- **< 99%** → Lower Tail (cheap end; live: dual resting longshot bids, formerly Maker Edge).
- Strength: signed distance from 99%. Lower Tail **≤ 98%** pins strength to max.
- Dead zone around 99%: watch only, no size from the meter.
- Smooth with MA / MA combo (details TBD).
- Side flips expected rare. BTC is the persistent Lower Tail case in ~9 months of backtests (volume). Main live use: dead-zone detection + strength-based sizing, not frequent flipping.

Product names are Upper Tail / Lower Tail (which end of the book). Execution differs: Upper Tail takes/triggers at the expensive rail; Lower Tail rests at the longshot rail.

The 2026-10-31 CORE doc keeps this break-even story and expands it into an explicit dual-rail live probe (UT WR vs ~99%, LT WR vs ~1%) as the main v4 strategies.
