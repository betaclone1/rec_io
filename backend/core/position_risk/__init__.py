"""Position risk library (HWS LVWAP stop decisions).

Safety: PRE never calls TM/TE, never places orders. ATS remains sole close authority.
PRE runs on local/non-prod only (hard-disabled on production hosts).
"""

from __future__ import annotations

OBSERVE_ONLY = True  # PRE never places orders
STAGE = 2
PROCESS_NAME = "position_risk_engine"

# Retained for legacy env references / docs; not required to start PRE locally.
ENV_ENABLE = "REC_ENABLE_POSITION_RISK_ENGINE"
ENV_MODE = "REC_POSITION_RISK_MODE"
ENV_PAPER_ARM = "REC_POSITION_RISK_PAPER_ARM"
ENV_ATS_CONSUME = "REC_POSITION_RISK_ATS_CONSUME"

POLICY_HWS_LVW_V1 = "hws_lvw_v1"
POLICY_ALLOWLIST = frozenset({POLICY_HWS_LVW_V1})

POSITION_RISK_MODES = frozenset({"legacy", "shadow", "paper"})
