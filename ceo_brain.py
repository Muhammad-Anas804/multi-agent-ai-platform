# agents/ceo_brain.py  —  Phase 1
from __future__ import annotations
import logging, re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)
MODEL_NAME, MAX_TOKENS, TEMPERATURE = "llama-3.3-70b-versatile", 2048, 0.65

class RequestType(str, Enum):
    NEW_IDEA = "new_idea"; FOLLOW_UP = "follow_up"
    ANALYSIS = "analysis"; DECISION = "decision"
    ROADMAP  = "roadmap";  CONVERSATION = "conversation"

def classify_request(text: str) -> RequestType:
    t = text.lower()
    if any(k in t for k in {"start","launch","build","create","startup","idea"}): return RequestType.NEW_IDEA
    if any(k in t for k in {"roadmap","plan","timeline","phases","milestones"})  : return RequestType.ROADMAP
    if any(k in t for k in {"should i","decide","hire","invest","pivot"})        : return RequestType.DECISION
    if any(k in t for k in {"analys","research","market","competitor"})          : return RequestType.ANALYSIS
    return RequestType.CONVERSATION

@dataclass
class CEOResponse:
    raw: str; request_type: RequestType
    idea_analysis: Optional[str] = None; recommendation: Optional[str] = None
    roadmap: Optional[str] = None;       immediate_actions: Optional[str] = None
    key_risks: Optional[str] = None;     verdict: Optional[str] = field(default=None, init=False)
    def __post_init__(self): self.verdict = next((k for k in ("NO-GO","PIVOT","GO") if k in (self.recommendation or self.raw).upper()), None)
    def summary(self) -> str: return f"[{self.request_type.value}]{f' [{self.verdict}]' if self.verdict else ''} — {len(self.raw)} chars"

_SECTIONS = [
    (r"(?:##?\s*)?(?:1\.)?\s*(?:IDEA\s+ANALYSIS|ANALYSIS)", "idea_analysis"),
    (r"(?:##?\s*)?(?:2\.)?\s*STRATEGIC\s+RECOMMENDATION",   "recommendation"),
    (r"(?:##?\s*)?(?:3\.)?\s*(?:ROADMAP|PLAN)",             "roadmap"),
    (r"(?:##?\s*)?(?:4\.)?\s*IMMEDIATE\s+ACTIONS?",          "immediate_actions"),
    (r"(?:##?\s*)?(?:5\.)?\s*KEY\s+RISKS?",                  "key_risks"),
]

def parse_response(raw: str, rtype: RequestType) -> CEOResponse:
    all_h  = "|".join(f"(?:{p})" for p,_ in _SECTIONS)
    chunks = re.compile(rf"(?=(?:{all_h}))", re.I|re.M).split(raw)
    secs: dict[str,str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        for pat, fname in _SECTIONS:
            if re.match(pat, chunk, re.I):
                secs[fname] = re.sub(rf"^{pat}\s*\n?","",chunk,count=1,flags=re.I).strip()
                break
    return CEOResponse(raw=raw, request_type=rtype, **{k: secs.get(k) for k in
        ["idea_analysis","recommendation","roadmap","immediate_actions","key_risks"]})

_SYSTEM = """\
You are an elite CEO Agent — world-class strategic advisor with 25 years
building companies across SaaS, AI, and consumer tech.
For NEW IDEAS use exactly these headers:
## IDEA ANALYSIS
## STRATEGIC RECOMMENDATION
## ROADMAP
## IMMEDIATE ACTIONS
## KEY RISKS
Be decisive. Real numbers. No filler."""

def build_system_prompt(long_term_context: str = "") -> str:
    if long_term_context.strip():
        return _SYSTEM + f"\n\n─── LONG-TERM MEMORY ───\n{long_term_context.strip()}\n────────────────────────"
    return _SYSTEM

class CEOBrain:
    def __init__(self, api_key: str, model: str = MODEL_NAME,
                 temperature: float = TEMPERATURE, max_tokens: int = MAX_TOKENS):
        self.llm = ChatGroq(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.model = model
        logger.info(f"CEOBrain ready (model={model})")

    def think(self, user_input: str,
              conversation_history: list[HumanMessage|AIMessage]|None = None,
              long_term_context: str = "") -> CEOResponse:
        rtype    = classify_request(user_input)
        messages = [SystemMessage(content=build_system_prompt(long_term_context))]
        messages += (conversation_history or [])
        messages.append(HumanMessage(content=user_input))
        try:
            raw = self.llm.invoke(messages).content
            raw = raw if isinstance(raw, str) else str(raw)
        except Exception as exc:
            raise RuntimeError(f"CEOBrain LLM failed: {exc}") from exc
        response = parse_response(raw.strip(), rtype)
        logger.info(f"CEOBrain → {response.summary()}")
        return response

    def health_check(self) -> bool:
        try: self.llm.invoke([HumanMessage(content="Reply: OK")]); return True
        except Exception: return False
