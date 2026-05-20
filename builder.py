# graph/builder.py  —  Phase 1
from __future__ import annotations
import os, logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from State           import AgentState
from marketing_agent import marketing_node
from finance_agent   import finance_node
from risk_agent      import risk_node
logger = logging.getLogger(__name__)


# ── Research node (inline — no separate class needed) ────────
def research_node(state: AgentState) -> AgentState:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        errors = list(state.get("errors", []))
        errors.append("ResearchAgent: no API key")
        return {**state, "research_output": "[Error: no API key]", "errors": errors}
    try:
        llm = ChatGroq(model="llama3-70b-8192", api_key=api_key, temperature=0.3, max_tokens=1024)
        prompt = (
            f"Business idea: {state['user_input']}\n"
            f"Context: {state.get('company_context','none')}\n\n"
            "Return JSON only with keys: domain, key_columns, target_audience, "
            "key_competitors, market_opportunity, critical_assumptions"
        )
        raw = llm.invoke([
            SystemMessage(content="You are a senior business research analyst. Be specific and concise."),
            HumanMessage(content=prompt),
        ]).content
        log = list(state.get("agent_log", []))
        log.append({"agent":"ResearchAgent","timestamp":datetime.now().isoformat(),
                    "status":"success","output_length":len(raw)})
        return {**state, "research_output": raw, "agent_log": log}
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"ResearchAgent: {exc}")
        return {**state, "research_output": f"[Failed: {exc}]", "errors": errors}


# ── CEO synthesis node ────────────────────────────────────────
def ceo_synthesis_node(state: AgentState) -> AgentState:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        errors = list(state.get("errors", []))
        errors.append("CEOAgent: no API key")
        return {**state, "final_output": "[Error: no API key]", "errors": errors}
    try:
        llm = ChatGroq(model="llama3-70b-8192", api_key=api_key, temperature=0.5, max_tokens=2048)
        prompt = f"""
You are the CEO. Synthesise all team reports into an executive decision memo.

User Request: {state['user_input']}
Research:  {state.get('research_output','')[:400]}
Marketing: {state.get('marketing_output','')[:400]}
Finance:   {state.get('finance_output','')[:400]}
Risk:      {state.get('risk_output','')[:400]}

Use these exact headers:
## EXECUTIVE SUMMARY
## STRATEGIC RECOMMENDATION (GO / NO-GO / PIVOT)
## PRIORITY ACTIONS (Next 30 Days)
## 90-DAY ROADMAP
## FINAL DECISION
"""
        raw = llm.invoke([
            SystemMessage(content="You are a visionary CEO. Be decisive. Boardroom-ready output."),
            HumanMessage(content=prompt),
        ]).content
        log = list(state.get("agent_log", []))
        log.append({"agent":"CEOSynthesis","timestamp":datetime.now().isoformat(),
                    "status":"success","output_length":len(raw)})
        return {**state, "final_output": raw, "agent_log": log}
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"CEOSynthesis: {exc}")
        return {**state, "final_output": f"[Failed: {exc}]", "errors": errors}


# ── Error gate ────────────────────────────────────────────────
def check_error(state: AgentState) -> str:
    """Route to END early if a critical error occurred."""
    return "error" if state.get("errors") else "continue"


# ── Graph builder ─────────────────────────────────────────────
def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("research",    research_node)
    builder.add_node("marketing",   marketing_node)
    builder.add_node("finance",     finance_node)
    builder.add_node("risk",        risk_node)
    builder.add_node("ceo",         ceo_synthesis_node)

    builder.set_entry_point("research")

    builder.add_conditional_edges("research", check_error, {
        "error":    END,
        "continue": "marketing",
    })
    builder.add_edge("marketing", "finance")
    builder.add_edge("finance",   "risk")
    builder.add_edge("risk",      "ceo")
    builder.add_edge("ceo",       END)

    logger.info("Graph compiled: research → marketing → finance → risk → CEO")
    return builder.compile()