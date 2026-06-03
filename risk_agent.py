# agents/risk_agent.py  —  Phase 3
from __future__ import annotations
import logging, re, os
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)
MODEL_NAME, MAX_TOKENS, TEMPERATURE = "llama-3.3-70b-versatile", 2048, 0.4

@dataclass
class RiskResponse:
    raw: str
    market_risks: Optional[str]=None;    execution_risks: Optional[str]=None
    financial_risks: Optional[str]=None; legal_risks: Optional[str]=None
    severity_matrix: Optional[str]=None; mitigations: Optional[str]=None
    def summary(self) -> str: return f"[risk] — {len(self.raw)} chars"

_SECTIONS = [
    (r"(?:##?\s*)?(?:1\.)?\s*MARKET\s+RISKS?",                   "market_risks"),
    (r"(?:##?\s*)?(?:2\.)?\s*EXECUTION\s+RISKS?",                 "execution_risks"),
    (r"(?:##?\s*)?(?:3\.)?\s*FINANCIAL\s+RISKS?",                 "financial_risks"),
    (r"(?:##?\s*)?(?:4\.)?\s*(?:LEGAL|COMPLIANCE)\s+RISKS?",      "legal_risks"),
    (r"(?:##?\s*)?(?:5\.)?\s*(?:RISK\s+)?SEVERITY\s+(?:MATRIX)?", "severity_matrix"),
    (r"(?:##?\s*)?(?:6\.)?\s*MITIGATION\s+(?:STRATEGIES?)?",      "mitigations"),
]

def parse_response(raw: str) -> RiskResponse:
    all_h  = "|".join(f"(?:{p})" for p,_ in _SECTIONS)
    chunks = re.compile(rf"(?=(?:{all_h}))", re.I|re.M).split(raw)
    secs: dict[str,str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        for pat, fname in _SECTIONS:
            if re.match(pat, chunk, re.I):
                secs[fname] = re.sub(rf"^{pat}\s*\n?","",chunk,count=1,flags=re.I).strip()
                break
    return RiskResponse(raw=raw, **{k: secs.get(k) for k in
        ["market_risks","execution_risks","financial_risks","legal_risks","severity_matrix","mitigations"]})

_SYSTEM = """\
You are a Chief Risk Officer (CRO) and strategic advisor.
Stress-test business plans honestly. You are a protector, not a blocker.
High/Medium/Low severity for every risk. Always include mitigation.

OUTPUT FORMAT (exact headers):
## MARKET RISKS
## EXECUTION RISKS
## FINANCIAL RISKS
## LEGAL & COMPLIANCE RISKS
## RISK SEVERITY MATRIX
## MITIGATION STRATEGIES"""

class RiskAgent:
    def __init__(self, api_key: str, model: str=MODEL_NAME,
                 temperature: float=TEMPERATURE, max_tokens: int=MAX_TOKENS):
        self.llm = ChatGroq(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.model = model
        logger.info(f"RiskAgent ready (model={model})")

    def run(self, user_input: str, research_output: str="",
            marketing_output: str="", finance_output: str="") -> RiskResponse:
        context = ""
        if research_output:  context += f"\n─── RESEARCH ───\n{research_output[:400]}\n"
        if marketing_output: context += f"\n─── MARKETING ───\n{marketing_output[:300]}\n"
        if finance_output:   context += f"\n─── FINANCE ───\n{finance_output[:300]}\n"
        user_prompt = (f"Identify all material risks for:\n{user_input}\n{context}\n"
                       "Be direct. Every risk needs severity and mitigation.")
        raw = self._call_llm(_SYSTEM, user_prompt)
        response = parse_response(raw)
        logger.info(f"RiskAgent → {response.summary()}")
        return response

    def _call_llm(self, system: str, user: str) -> str:
        try:
            r = self.llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            return (r.content if isinstance(r.content, str) else str(r.content)).strip()
        except Exception as exc:
            raise RuntimeError(f"RiskAgent LLM failed: {exc}") from exc

    def health_check(self) -> bool:
        try: self.llm.invoke([HumanMessage(content="Reply: OK")]); return True
        except Exception: return False

def risk_node(state: dict) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        errors = list(state.get("errors",[])); errors.append("RiskAgent: no API key")
        return {**state, "risk_output":"[Error: no API key]", "errors": errors}
    try:
        result = RiskAgent(api_key=api_key).run(
            state.get("user_input",""), state.get("research_output",""),
            state.get("marketing_output",""), state.get("finance_output",""))
        log = list(state.get("agent_log",[]))
        log.append({"agent":"RiskAgent","timestamp":datetime.now().isoformat(),
                    "status":"success","output_length":len(result.raw)})
        return {**state, "risk_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state.get("errors",[])); errors.append(f"RiskAgent: {exc}")
        return {**state, "risk_output": f"[Failed: {exc}]", "errors": errors}
