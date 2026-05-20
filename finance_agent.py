# agents/finance_agent.py  —  Phase 3
from __future__ import annotations
import logging, re, os
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)
MODEL_NAME, MAX_TOKENS, TEMPERATURE = "llama-3.3-70b-versatile", 2048, 0.2

class FinanceFocus(str, Enum):
    STARTUP="startup"; GROWTH="growth"; PROFITABILITY="profitability"; GENERAL="general"

def classify_focus(text: str) -> FinanceFocus:
    t = text.lower()
    if any(k in t for k in {"start","launch","new","bootstrap"}): return FinanceFocus.STARTUP
    if any(k in t for k in {"scale","grow","raise","series"}):    return FinanceFocus.GROWTH
    if any(k in t for k in {"profit","margin","burn","cost"}):    return FinanceFocus.PROFITABILITY
    return FinanceFocus.GENERAL

@dataclass
class FinanceResponse:
    raw: str; focus: FinanceFocus
    startup_costs: Optional[str]=None;       operating_costs: Optional[str]=None
    revenue_projections: Optional[str]=None; break_even: Optional[str]=None
    roi_projection: Optional[str]=None;      funding_requirements: Optional[str]=None
    financial_risks: Optional[str]=None
    def summary(self) -> str: return f"[{self.focus.value}] — {len(self.raw)} chars"

_SECTIONS = [
    (r"(?:##?\s*)?(?:1\.)?\s*STARTUP\s+COST",                    "startup_costs"),
    (r"(?:##?\s*)?(?:2\.)?\s*(?:MONTHLY\s+)?OPERATING\s+COSTS?", "operating_costs"),
    (r"(?:##?\s*)?(?:3\.)?\s*REVENUE\s+PROJECTIONS?",            "revenue_projections"),
    (r"(?:##?\s*)?(?:4\.)?\s*BREAK.EVEN",                        "break_even"),
    (r"(?:##?\s*)?(?:5\.)?\s*ROI\s+PROJECTION",                  "roi_projection"),
    (r"(?:##?\s*)?(?:6\.)?\s*FUNDING\s+REQUIREMENTS?",           "funding_requirements"),
    (r"(?:##?\s*)?(?:7\.)?\s*(?:KEY\s+)?FINANCIAL\s+RISKS?",     "financial_risks"),
]

def parse_response(raw: str, focus: FinanceFocus) -> FinanceResponse:
    all_h  = "|".join(f"(?:{p})" for p,_ in _SECTIONS)
    chunks = re.compile(rf"(?=(?:{all_h}))", re.I|re.M).split(raw)
    secs: dict[str,str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        for pat, fname in _SECTIONS:
            if re.match(pat, chunk, re.I):
                secs[fname] = re.sub(rf"^{pat}\s*\n?","",chunk,count=1,flags=re.I).strip()
                break
    return FinanceResponse(raw=raw, focus=focus, **{k: secs.get(k) for k in
        ["startup_costs","operating_costs","revenue_projections","break_even",
         "roi_projection","funding_requirements","financial_risks"]})

_SYSTEM = """\
You are a CFO with 20 years of startup financial modelling experience.
Specific numbers, not ranges. State every assumption clearly.

OUTPUT FORMAT (exact headers):
## STARTUP COST ESTIMATE
## MONTHLY OPERATING COSTS
## REVENUE PROJECTIONS (Month 1 / Month 6 / Month 12)
## BREAK-EVEN ANALYSIS
## ROI PROJECTION (12 months)
## FUNDING REQUIREMENTS
## KEY FINANCIAL RISKS"""

class FinanceAgent:
    def __init__(self, api_key: str, model: str=MODEL_NAME,
                 temperature: float=TEMPERATURE, max_tokens: int=MAX_TOKENS):
        self.llm = ChatGroq(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.model = model
        logger.info(f"FinanceAgent ready (model={model})")

    def run(self, user_input: str, research_output: str="", marketing_output: str="") -> FinanceResponse:
        focus = classify_focus(user_input)
        context = ""
        if research_output:  context += f"\n─── RESEARCH BRIEF ───\n{research_output[:500]}\n"
        if marketing_output: context += f"\n─── MARKETING SUMMARY ───\n{marketing_output[:400]}\n"
        user_prompt = (f"Build a detailed financial model for:\n{user_input}\n{context}\n"
                       "Realistic numbers for a small team. State every assumption.")
        raw = self._call_llm(_SYSTEM, user_prompt)
        response = parse_response(raw, focus)
        logger.info(f"FinanceAgent → {response.summary()}")
        return response

    def _call_llm(self, system: str, user: str) -> str:
        try:
            r = self.llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            return (r.content if isinstance(r.content, str) else str(r.content)).strip()
        except Exception as exc:
            raise RuntimeError(f"FinanceAgent LLM failed: {exc}") from exc

    def health_check(self) -> bool:
        try: self.llm.invoke([HumanMessage(content="Reply: OK")]); return True
        except Exception: return False

def finance_node(state: dict) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        errors = list(state.get("errors",[])); errors.append("FinanceAgent: no API key")
        return {**state, "finance_output":"[Error: no API key]", "errors": errors}
    try:
        result = FinanceAgent(api_key=api_key).run(
            state.get("user_input",""), state.get("research_output",""), state.get("marketing_output",""))
        log = list(state.get("agent_log",[]))
        log.append({"agent":"FinanceAgent","timestamp":datetime.now().isoformat(),
                    "status":"success","output_length":len(result.raw)})
        return {**state, "finance_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state.get("errors",[])); errors.append(f"FinanceAgent: {exc}")
        return {**state, "finance_output": f"[Failed: {exc}]", "errors": errors}
