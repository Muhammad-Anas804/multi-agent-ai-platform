# graph/state.py  —  Phase 1
from __future__ import annotations
from typing import TypedDict, Optional

class AgentState(TypedDict):
    # ── Input ─────────────────────────────────
    user_input:       str
    company_context:  str
    run_id:           str
    timestamp:        str

    # ── Agent outputs ─────────────────────────
    research_output:  str
    ceo_direction:    str       # CEO's initial GO/NO-GO before other agents
    marketing_output: str
    finance_output:   str
    risk_output:      str
    final_output:     str      # CEO's final synthesis

    # ── Audit ─────────────────────────────────
    errors:           list[str]
    agent_log:        list[dict]