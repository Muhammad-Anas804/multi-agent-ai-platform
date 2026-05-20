# api.py — FastAPI Backend
# Run: python api.py
# Then open: http://localhost:8000

import os, sys, json, asyncio
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

from ceo_brain       import CEOBrain
from marketing_agent import MarketingAgent
from finance_agent   import FinanceAgent
from risk_agent      import RiskAgent
from State           import AgentState

app = FastAPI(title="CEO Agent SaaS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class IdeaRequest(BaseModel):
    idea: str
    context: str = ""

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/run")
async def run_agents(req: IdeaRequest):
    async def generate():
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        state: AgentState = {
            "user_input": req.idea, "company_context": req.context,
            "run_id": run_id, "timestamp": datetime.now().isoformat(),
            "research_output": "", "ceo_direction": "",
            "marketing_output": "", "finance_output": "",
            "risk_output": "", "final_output": "",
            "errors": [], "agent_log": [],
        }

        def send(event, data):
            return f"data: {json.dumps({'event': event, **data})}\n\n"

        yield send("start", {"run_id": run_id})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Research", "icon": "📊"})
        try:
            r = CEOBrain(api_key=GROQ_API_KEY).think(
                f"Research this business idea: {req.idea}\nCover: market size, target audience, top 3 competitors, opportunity.")
            state["research_output"] = r.raw
            state["ceo_direction"]   = r.recommendation or ""
            yield send("agent_done", {"agent": "Research", "output": r.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Research", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Marketing", "icon": "📣"})
        try:
            result = MarketingAgent(api_key=GROQ_API_KEY).run(req.idea, state["research_output"], state["ceo_direction"])
            state["marketing_output"] = result.raw
            yield send("agent_done", {"agent": "Marketing", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Marketing", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Finance", "icon": "💰"})
        try:
            result = FinanceAgent(api_key=GROQ_API_KEY).run(req.idea, state["research_output"], state["marketing_output"])
            state["finance_output"] = result.raw
            yield send("agent_done", {"agent": "Finance", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Finance", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Risk", "icon": "⚠️"})
        try:
            result = RiskAgent(api_key=GROQ_API_KEY).run(req.idea, state["research_output"], state["marketing_output"], state["finance_output"])
            state["risk_output"] = result.raw
            yield send("agent_done", {"agent": "Risk", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Risk", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "CEO Decision", "icon": "👔"})
        try:
            result = CEOBrain(api_key=GROQ_API_KEY).think(
                f"Synthesise all reports into final executive decision.\nRequest: {req.idea}\n"
                f"Research:\n{state['research_output'][:500]}\nMarketing:\n{state['marketing_output'][:500]}\n"
                f"Finance:\n{state['finance_output'][:500]}\nRisk:\n{state['risk_output'][:500]}")
            state["final_output"] = result.raw
            yield send("agent_done", {"agent": "CEO Decision", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "CEO Decision", "error": str(e)})

        yield send("complete", {"run_id": run_id, "state": state})

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)