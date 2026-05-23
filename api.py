# api.py — FastAPI Backend + Authentication
# Run: python api.py

import os, sys, json, asyncio, sqlite3, hashlib, hmac, secrets, base64, time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SECRET_KEY = os.getenv("JWT_SECRET", "change-me-in-production-use-long-random-string")
DB_PATH = os.getenv("DB_PATH", "users.db")

from ceo_brain import CEOBrain
from marketing_agent import MarketingAgent
from finance_agent import FinanceAgent
from risk_agent import RiskAgent
from State import AgentState

app = FastAPI(title="CEO Agent SaaS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ════════════════════════════════════════════════════════════
# DATABASE
# ════════════════════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ════════════════════════════════════════════════════════════
# PASSWORD HASHING
# ════════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"{salt}:{h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":")
        new_h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
        return hmac.compare_digest(h, new_h.hex())
    except Exception:
        return False

# ════════════════════════════════════════════════════════════
# JWT
# ════════════════════════════════════════════════════════════
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64url(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)

def create_token(user_id: int, email: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": user_id, "email": email,
        "exp": int(time.time()) + 60 * 60 * 24 * 7
    }).encode())
    sig = _b64url(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"

def verify_token(token: str) -> dict:
    try:
        header, payload, sig = token.split(".")
        expected = _b64url(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("Invalid signature")
        data = json.loads(_b64url(_unb64url(payload)))
        if data["exp"] < int(time.time()):
            raise ValueError("Token expired")
        return data
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

bearer = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_token(credentials.credentials)

# ════════════════════════════════════════════════════════════
# REQUEST MODELS
# ════════════════════════════════════════════════════════════
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

# ════════════════════════════════════════════════════════════
# AUTH ROUTES
# ════════════════════════════════════════════════════════════
@app.post("/auth/signup")
def signup(req: SignupRequest):
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if len(req.name.strip()) < 2:
        raise HTTPException(400, "Name must be at least 2 characters")
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (req.email.lower().strip(), req.name.strip(),
             hash_password(req.password), datetime.utcnow().isoformat())
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email = ?", (req.email.lower().strip(),)).fetchone()
        token = create_token(row["id"], req.email.lower().strip())
        return {"token": token, "name": req.name.strip(), "email": req.email.lower().strip()}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Email already registered")
    finally:
        conn.close()

@app.post("/auth/login")
def login(req: LoginRequest):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (req.email.lower().strip(),)
        ).fetchone()
        if not row or not verify_password(req.password, row["password_hash"]):
            raise HTTPException(401, "Invalid email or password")
        token = create_token(row["id"], row["email"])
        return {"token": token, "name": row["name"], "email": row["email"]}
    finally:
        conn.close()

@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?", (user["sub"],)
        ).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return {"name": row["name"], "email": row["email"], "created_at": row["created_at"]}
    finally:
        conn.close()

# ════════════════════════════════════════════════════════════
# MAIN ROUTES
# ════════════════════════════════════════════════════════════
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
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
