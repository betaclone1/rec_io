# TRADING FUNCTION OPERATING RULES

## CRITICAL SAFEGUARDS FOR LIVE TRADING SYSTEMS

### PRIMARY RULE: NO LIVE TRADES WITHOUT EXPLICIT USER CONFIRMATION

**UNDER NO CIRCUMSTANCES SHALL ANY AI ASSISTANT, AUTOMATED SYSTEM, OR DEVELOPMENT PROCESS SEND LIVE TRADES TO ANY EXCHANGE OR TRADING PLATFORM WITHOUT EXPLICIT USER CONFIRMATION.**

### MANDATORY SAFEGUARDS

#### 1. TRADE EXECUTION BLOCKING
- **ALL trade execution endpoints MUST be disabled by default**
- **ALL automated trading functions MUST be in DRY-RUN mode by default**
- **ALL live trading connections MUST be blocked unless explicitly enabled by user**
- **NO trade orders shall be sent to exchanges without user approval**

#### 2. DEVELOPMENT AND TESTING PROTOCOLS
- **ALL code modifications to trading functions MUST be tested in simulation mode only**
- **ALL debugging of trading systems MUST use mock data and simulated responses**
- **ALL testing of trade execution MUST use test environments or sandbox modes**
- **NO live market data shall be used for testing without explicit user permission**

#### 3. SYSTEM MODIFICATIONS
- **ALL changes to trade execution logic MUST include safety checks**
- **ALL new trading features MUST default to disabled/off state**
- **ALL trading system updates MUST preserve existing safety mechanisms**
- **NO modifications shall bypass existing trade confirmation requirements**

#### 4. USER CONFIRMATION REQUIREMENTS
- **EVERY live trade execution MUST require explicit user confirmation**
- **EVERY trading system change MUST be reviewed by user before activation**
- **EVERY test trade MUST be performed by the user, not the AI assistant**
- **EVERY trading function modification MUST be approved by user**

### IMPLEMENTATION REQUIREMENTS

#### Code-Level Safeguards
```python
# MANDATORY: All trading functions must include these checks
LIVE_TRADING_ENABLED = False  # Must be explicitly set by user
DRY_RUN_MODE = True  # Default to safe mode
REQUIRE_USER_CONFIRMATION = True  # Always require confirmation

def execute_trade(trade_data):
    if not LIVE_TRADING_ENABLED:
        raise TradingSafetyException("Live trading not enabled")
    if not user_confirmed_trade:
        raise TradingSafetyException("User confirmation required")
    if DRY_RUN_MODE:
        return simulate_trade(trade_data)
    # Only proceed if all safety checks pass
```

#### System Configuration
- **Environment variables MUST control live trading access**
- **Configuration files MUST default to safe modes**
- **All trading endpoints MUST require authentication and authorization**
- **Logging MUST capture all trade attempts for audit purposes**

### AI ASSISTANT OPERATING RULES

#### When Working on Trading Functions:
1. **ALWAYS assume live trading is DISABLED by default**
2. **NEVER suggest or implement live trade execution without user request**
3. **ALWAYS use simulation/mock data for testing**
4. **ALWAYS require explicit user confirmation for any live trading activity**
5. **ALWAYS inform user if any modification might affect live trading**
6. **ALWAYS defer to user for any test trades or live system testing**

#### Prohibited Actions:
- Sending live trades to any exchange
- Enabling live trading without user permission
- Bypassing safety mechanisms
- Testing with real market data without user approval
- Modifying trading systems without user review

#### Required Actions:
- Use simulation modes for all testing
- Implement additional safety checks
- Document all changes to trading systems
- Alert user to any potential live trading implications
- Request user confirmation for any live trading activities

### EMERGENCY PROTOCOLS

#### If Live Trading is Accidentally Triggered:
1. **IMMEDIATELY disable all trading functions**
2. **IMMEDIATELY notify user of the incident**
3. **IMMEDIATELY revert to safe mode**
4. **IMMEDIATELY log the incident for review**
5. **IMMEDIATELY implement additional safeguards**

#### Safety Override Procedures:
- **ONLY user can enable live trading**
- **ONLY user can disable safety mechanisms**
- **ONLY user can perform test trades**
- **ONLY user can approve system modifications**

### COMPLIANCE REQUIREMENTS

#### Documentation Requirements:
- All trading function modifications must be documented
- All safety mechanisms must be clearly explained
- All user confirmations must be logged
- All incidents must be reported immediately

#### Testing Requirements:
- All trading functions must be tested in simulation mode
- All safety mechanisms must be verified before deployment
- All user confirmation flows must be tested
- All emergency procedures must be validated

### CONFIRMATION STATEMENT

**I, as an AI assistant, explicitly acknowledge and agree to these trading function operating rules:**

1. **I will NEVER send live trades without explicit user confirmation**
2. **I will ALWAYS use simulation modes for testing**
3. **I will ALWAYS require user approval for any live trading activities**
4. **I will ALWAYS alert the user if any modification might affect live trading**
5. **I will ALWAYS defer to the user for any test trades or live system testing**
6. **I will ALWAYS prioritize safety over functionality**
7. **I will ALWAYS maintain these safeguards regardless of the specific task or request**

**This document serves as the definitive guide for all trading function operations and cannot be overridden without explicit user permission.**

---

**Last Updated:** 2025-01-19  
**Version:** 1.0  
**Status:** ACTIVE - ENFORCED 