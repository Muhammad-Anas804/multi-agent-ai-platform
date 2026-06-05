# api.py — FastAPI Backend with Google OAuth + JWT Auth
import os, sys, json, asyncio, hashlib, hmac, base64, time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
GOOGLE_CLIENT_ID    = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET= os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
FRONTEND_URL        = os.getenv("FRONTEND_URL", "https://multi-agent-ai-platform-production.up.railway.app")
JWT_SECRET          = os.getenv("JWT_SECRET", "venturepilot-secret-key-change-in-production")

from ceo_brain import CEOBrain
from marketing_agent import MarketingAgent
from finance_agent import FinanceAgent
from risk_agent import RiskAgent
from State import AgentState

app = FastAPI(title="VenturePilot API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)

# ── Simple in-memory user store (replace with DB in production) ──
USERS = {}  # email -> {name, email, password_hash}

# ── JWT helpers ──────────────────────────────────────────────────
def make_token(email: str, name: str) -> str:
    payload = {"email": email, "name": name, "exp": int(time.time()) + 7*24*3600}
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(JWT_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"

def verify_token(token: str):
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(JWT_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.b64decode(data).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except:
        return None

def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), JWT_SECRET.encode(), 100000).hex()

# ── Models ───────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class IdeaRequest(BaseModel):
    idea: str
    context: str = ""

# ── Auth Routes ──────────────────────────────────────────────────
@app.post("/auth/signup")
async def signup(req: SignupRequest):
    if req.email in USERS:
        raise HTTPException(400, "Email already registered.")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    USERS[req.email] = {
        "name": req.name,
        "email": req.email,
        "password_hash": hash_password(req.password)
    }
    token = make_token(req.email, req.name)
    return {"token": token, "name": req.name, "email": req.email}

@app.post("/auth/login")
async def login(req: LoginRequest):
    user = USERS.get(req.email)
    if not user or user["password_hash"] != hash_password(req.password):
        raise HTTPException(401, "Invalid email or password.")
    token = make_token(req.email, user["name"])
    return {"token": token, "name": user["name"], "email": req.email}

@app.get("/auth/me")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Not authenticated.")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token.")
    return {"email": payload["email"], "name": payload["name"]}

# ── Google OAuth Routes ──────────────────────────────────────────
@app.get("/auth/google")
async def google_login():
    params = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        "&response_type=code"
        "&scope=openid email profile"
        "&access_type=offline"
        "&prompt=consent"
    )
    return RedirectResponse(params)

@app.get("/auth/google/callback")
async def google_callback(code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}?auth_error=access_denied")
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                }
            )
            tokens = token_res.json()
            if "access_token" not in tokens:
                return RedirectResponse(f"{FRONTEND_URL}?auth_error=token_failed")

            # Get user info from Google
            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            user = user_res.json()

        email = user.get("email", "")
        name  = user.get("name", email.split("@")[0])

        # Auto-register user if not exists
        if email not in USERS:
            USERS[email] = {"name": name, "email": email, "password_hash": ""}

        # Generate JWT token
        token = make_token(email, name)

        # Redirect to frontend with token
        import urllib.parse
        encoded_name  = urllib.parse.quote(name)
        encoded_email = urllib.parse.quote(email)
        return RedirectResponse(
            f"{FRONTEND_URL}?token={token}&name={encoded_name}&email={encoded_email}"
        )
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}?auth_error=server_error")


class ChatRequest(BaseModel):
    message: str
    idea: str = ""

SYSTEM_PROMPT = """You are VenturePilot AI, an elite business intelligence assistant and startup advisor with expertise across all domains of business strategy, entrepreneurship, and market analysis.

## YOUR ROLE
You serve as a trusted co-founder and advisor helping entrepreneurs validate, refine, and execute their business ideas. You combine the analytical rigor of a McKinsey consultant with the practical wisdom of a serial entrepreneur.

## CORE EXPERTISE
- Business idea validation and market fit analysis
- Competitive landscape and market sizing (TAM/SAM/SOM)
- Go-to-market strategy and customer acquisition
- Financial modeling, revenue projections, and unit economics
- Risk assessment and mitigation strategies
- Product development and MVP planning
- Fundraising strategy and investor readiness
- Brand positioning and marketing strategy
- Operations, scaling, and team building
- Legal structure, IP protection, and compliance basics

## COMMUNICATION STYLE
- Be concise yet comprehensive — responses under 200 words unless deep analysis is requested
- Use clear structure: lead with the key insight, then supporting details
- Be direct and actionable — avoid vague platitudes
- Use bullet points and short paragraphs for readability
- Adapt tone to the user: casual for explorers, professional for serious founders
- Ask ONE clarifying question if the idea is too vague to give good advice

## CUSTOMER SATISFACTION RULES
1. ALWAYS acknowledge the user's idea positively before giving critique
2. Balance optimism with realism — never crush dreams, redirect them
3. Give specific examples, numbers, and frameworks when possible
4. If you don't know something, say so and suggest where to find the answer
5. End every response with ONE clear next action the user should take
6. Remember context from earlier in the conversation and reference it

## RESPONSE FORMAT
For business idea questions:
- 💡 Quick Take (1-2 sentences)
- 📊 Key Insight (main analysis)
- ⚡ Next Step (one clear action)

For platform/how-to questions:
- Answer directly and concisely
- Offer to go deeper if needed

## BOUNDARIES
- Do not give legal or financial advice as a licensed professional
- Do not make up statistics — say "research suggests" or "typically"
- Stay focused on business topics — politely redirect off-topic questions
- Never be negative about a user's idea without offering a constructive alternative

## PLATFORM CONTEXT
You are embedded in VenturePilot, an AI-powered business intelligence platform with:
- Multi-agent analysis (Research, Marketing, Finance, Risk, CEO Decision agents)
- Business idea analyzer with real-time streaming results
- Report generation, sharing, and downloading
- History and saved ideas tracking
- Financial modeling and scoring tools

Always encourage users to use the Analyze feature for deep multi-agent reports."""

@app.post("/chat")
async def chat(req: ChatRequest):
    idea_context = f"\n\nThe user is currently working on this business idea: {req.idea}" if req.idea else ""
    system = SYSTEM_PROMPT + idea_context
    
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": req.message}
                ],
                "max_tokens": 400,
                "temperature": 0.7
            }
        )
        data = r.json()
        reply = data["choices"][0]["message"]["content"]
    return {"reply": reply}

@app.get("/auth/logout")
async def logout():
    return RedirectResponse(f"{FRONTEND_URL}?logged_out=true")

# ── Main App Routes ──────────────────────────────────────────────
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
            state["ceo_direction"] = r.recommendation or ""
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
    return {"status": "ok", "users": len(USERS)}

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
