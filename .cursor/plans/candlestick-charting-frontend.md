# Candlestick charting (major frontend)

**Goal:** Build a candlestick charting system using internally collected OHLC symbol price data, with TradingView-style charts integrated into the trade history UI and usable for future backtesting/analysis.
**Scope:** In: frontend candlestick components, backend data access for OHLC series, and integration into existing UIs where charting adds clear value (e.g. trade history detail views). Out: full backtesting UI (would need a separate plan once charting is in place).
**Status:** draft (long-term frontend initiative)

## Steps
1. Document available OHLC data sources (e.g. `historical_data.*_price_history`, live tables) and their shapes.
2. Design the frontend charting approach (library choice or custom implementation, theming, interaction patterns).
3. Implement a reusable candlestick chart component that can be fed OHLC data for a symbol/time range.
4. Integrate the chart into at least one concrete UI surface (e.g. trade history detail drawer/page) with appropriate controls (zoom, pan, timeframe).
5. Plan for how this charting stack could be reused or extended for future backtesting views.

## Completion criteria
- [ ] We have a clear mapping from our OHLC data sources into the charting component’s input format.
- [ ] A production-quality candlestick chart component exists and matches the app’s visual standards.
- [ ] At least one user-facing screen shows these charts in a useful way.
- [ ] The implementation leaves a clear path for reuse in future backtesting/analysis UIs.

## Blockers / decisions
- Choose charting tech (pure SVG/Canvas vs a library) and align on UX expectations before deep implementation.

