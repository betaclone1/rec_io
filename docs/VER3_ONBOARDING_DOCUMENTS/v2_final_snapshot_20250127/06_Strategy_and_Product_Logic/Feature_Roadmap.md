# Feature Roadmap – REC.IO

## Purpose
Define the prioritized feature development plan for REC.IO from the current v2 state through v3 launch and beyond. BMAD agents will use this as a guide for sequencing work and tracking progress.

---

## 1. v2 Finalization (Short Term – Immediate)
**Goals**: Stabilize current production, complete onboarding documentation, deploy to DigitalOcean.

**Key Tasks**:
- [x] Complete System Documentation Checklist
- [ ] Finalize PostgreSQL migration (remove legacy SQLite/JSON writes)
- [ ] Implement basic auto-stop for HOURLY HTC
- [ ] Frontend polish for trade monitor & indicators
- [ ] Integrate account sync with live trade view
- [ ] Bug fixes from live trading feedback

**Priority**: High – Required before v3 kick-off.

---

## 2. v3 Kick-Off (Medium Term – Next Major Release)
**Goals**: Transition to scalable multi-strategy, multi-market architecture with full automation capabilities.

**Core Initiatives**:
1. **Multi-Monitor, Multi-Strategy System**
   - Each user can run multiple monitors
   - Each monitor assigned a unique strategy & instrument
2. **Customizable Strategy Parameters**
   - Per-monitor control of probability thresholds, risk, stops
3. **Backtesting-Powered Strategy Development**
   - Run custom backtests using historical fingerprints
   - Save successful strategies in personal library
4. **Auto-Stop & Auto-Entry Enhancements**
   - Advanced triggers based on price, volatility, momentum
   - Take-profit automation
5. **Redis Integration**
   - Centralized caching & pub/sub for low-latency updates
   - **Master System Logging** - Unified event-driven logging system for critical system events
6. **Containerized Deployment**
   - DigitalOcean App Platform or Fly.io ready
   - Zero-downtime rolling upgrades
7. **Security Overhaul**
   - Replace plaintext .env with secrets manager
   - MFA for critical actions
8. **Advanced Monitoring & Alerting**
   - Service health dashboards
   - Alerting via push/SMS

---

## 3. v3+ Long-Term Roadmap
**Potential Additions** (priority TBD):
- Support for equities, indices, and other binary markets
- Strategy marketplace for community sharing
- AI-assisted parameter tuning
- Automated arbitrage detection
- Cross-account trade orchestration
- Fully modular plugin system for new indicators/data feeds

---

## 4. Prioritization Framework
**Ranking Criteria**:
- **Impact**: Effect on profitability, scalability, or stability
- **Complexity**: Development + integration effort
- **Risk**: Potential to destabilize existing workflows

**Tier Definitions**:
- **Tier 1** – Must have for v3 launch
- **Tier 2** – Nice to have in v3.x
- **Tier 3** – Future exploration

---

## 5. Next Steps for BMAD
1. Review v2 completion tasks – assign owners
2. Sequence v3 Tier 1 initiatives
3. Draft technical requirements for multi-monitor system
4. Schedule security overhaul design review
5. Begin container build prototype in parallel with v2 support
