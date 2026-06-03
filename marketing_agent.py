# agents/marketing_agent.py  —  Phase 3
from __future__ import annotations
import logging, re, os
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)
MODEL_NAME, MAX_TOKENS, TEMPERATURE = "llama-3.3-70b-versatile", 2048, 0.75

class MarketingFocus(str, Enum):
    LAUNCH="launch"; GROWTH="growth"; REPOSITIONING="repositioning"
    RETENTION="retention"; GENERAL="general"

def classify_focus(text: str) -> MarketingFocus:
    t = text.lower()
    if any(k in t for k in {"launch","start","new","first","introduce"}): return MarketingFocus.LAUNCH
    if any(k in t for k in {"grow","scale","expand","acquisition"}):      return MarketingFocus.GROWTH
    if any(k in t for k in {"reposition","rebrand","pivot"}):             return MarketingFocus.REPOSITIONING
    if any(k in t for k in {"retain","churn","loyalty","upsell"}):        return MarketingFocus.RETENTION
    return MarketingFocus.GENERAL

@dataclass
class MarketingResponse:
    raw: str; focus: MarketingFocus
    positioning: Optional[str]=None; segments: Optional[str]=None
    channels: Optional[str]=None;    messages: Optional[str]=None
    launch_plan: Optional[str]=None; kpis: Optional[str]=None
    def summary(self) -> str: return f"[{self.focus.value}] — {len(self.raw)} chars"

_SECTIONS = [
    (r"(?:##?\s*)?(?:1\.)?\s*POSITIONING(?:\s+STATEMENT)?", "positioning"),
    (r"(?:##?\s*)?(?:2\.)?\s*TARGET\s+SEGMENTS?",           "segments"),
    (r"(?:##?\s*)?(?:3\.)?\s*(?:MARKETING\s+)?CHANNELS?",   "channels"),
    (r"(?:##?\s*)?(?:4\.)?\s*KEY\s+MESSAGES?",              "messages"),
    (r"(?:##?\s*)?(?:5\.)?\s*(?:90.DAY\s+)?LAUNCH\s+PLAN",  "launch_plan"),
    (r"(?:##?\s*)?(?:6\.)?\s*(?:SUCCESS\s+METRICS?|KPIS?)", "kpis"),
]

def parse_response(raw: str, focus: MarketingFocus) -> MarketingResponse:
    all_h  = "|".join(f"(?:{p})" for p,_ in _SECTIONS)
    chunks = re.compile(rf"(?=(?:{all_h}))", re.I|re.M).split(raw)
    secs: dict[str,str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        for pat, fname in _SECTIONS:
            if re.match(pat, chunk, re.I):
                secs[fname] = re.sub(rf"^{pat}\s*\n?","",chunk,count=1,flags=re.I).strip()
                break
    return MarketingResponse(raw=raw, focus=focus, **{k: secs.get(k) for k in
        ["positioning","segments","channels","messages","launch_plan","kpis"]})

_SYSTEM = """\
You are a world-class CMO with 20 years launching products from zero to $100M ARR.
Specific over vague — name real channels, real tactics, real numbers.
One clear recommendation, not five options. Executable by a 1-3 person team.

OUTPUT FORMAT (exact headers):
## POSITIONING STATEMENT
## TARGET SEGMENTS
## MARKETING CHANNELS
## KEY MESSAGES
## 90-DAY LAUNCH PLAN
## SUCCESS METRICS (KPIs)"""

class MarketingAgent:
    def __init__(self, api_key: str, model: str=MODEL_NAME,
                 temperature: float=TEMPERATURE, max_tokens: int=MAX_TOKENS):
        self.llm = ChatGroq(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.model = model
        logger.info(f"MarketingAgent ready (model={model})")

    def run(self, user_input: str, research_output: str="", ceo_context: str="") -> MarketingResponse:
        focus = classify_focus(user_input)
        context = ""
        if research_output: context += f"\n─── RESEARCH BRIEF ───\n{research_output[:600]}\n"
        if ceo_context:     context += f"\n─── CEO DIRECTION ───\n{ceo_context[:300]}\n"
        user_prompt = (f"Create a full go-to-market strategy for:\n{user_input}\n{context}\n"
                       "Specific channels, real tactics, week-by-week 90-day plan.")
        raw = self._call_llm(_SYSTEM, user_prompt)
        response = parse_response(raw, focus)
        logger.info(f"MarketingAgent → {response.summary()}")
        return response

    def _call_llm(self, system: str, user: str) -> str:
        try:
            r = self.llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            return (r.content if isinstance(r.content, str) else str(r.content)).strip()
        except Exception as exc:
            raise RuntimeError(f"MarketingAgent LLM failed: {exc}") from exc

    def health_check(self) -> bool:
        try: self.llm.invoke([HumanMessage(content="Reply: OK")]); return True
        except Exception: return False

def marketing_node(state: dict) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        errors = list(state.get("errors",[])); errors.append("MarketingAgent: no API key")
        return {**state, "marketing_output":"[Error: no API key]", "errors": errors}
    try:
        result = MarketingAgent(api_key=api_key).run(
            state.get("user_input",""), state.get("research_output",""), state.get("ceo_direction",""))
        log = list(state.get("agent_log",[]))
        log.append({"agent":"MarketingAgent","timestamp":datetime.now().isoformat(),
                    "status":"success","output_length":len(result.raw)})
        return {**state, "marketing_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state.get("errors",[])); errors.append(f"MarketingAgent: {exc}")
        return {**state, "marketing_output": f"[Failed: {exc}]", "errors": errors}
