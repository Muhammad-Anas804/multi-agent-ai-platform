# api.py — FastAPI Backend + Authentication + Google OAuth
import os, sys, json, asyncio, sqlite3, hashlib, hmac, secrets, base64, time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from ceo_brain import CEOBrain
from marketing_agent import MarketingAgent
from finance_agent import FinanceAgent
from risk_agent import RiskAgent
from State import AgentState

GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
SECRET_KEY           = os.getenv("JWT_SECRET", "change-me-in-production")
DB_PATH              = os.getenv("DB_PATH", "users.db")
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "https://multi-agent-ai-platform-production.up.railway.app/auth/google/callback")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "https://multi-agent-ai-platform-production.up.railway.app")

app = FastAPI(title="VenturePilot API")
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
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            name          TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            plan          TEXT DEFAULT 'free',
            google_id     TEXT
        )
    """)
    # Add missing columns if upgrading old DB
    try:
        conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
    except: pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
    except: pass
    conn.commit()
    conn.close()

init_db()

# ════════════════════════════════════════════════════════════
# PASSWORD + JWT
# ════════════════════════════════════════════════════════════
def hash_password(p): 
    s = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", p.encode(), s.encode(), 260000)
    return f"{s}:{h.hex()}"

def verify_password(p, stored):
    try:
        s, h = stored.split(":")
        return hmac.compare_digest(h, hashlib.pbkdf2_hmac("sha256", p.encode(), s.encode(), 260000).hex())
    except: return False

def _b64url(data): return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
def _unb64url(s):
    return base64.urlsafe_b64decode(s + "=" * (4 - len(s) % 4))

def create_token(user_id, email):
    h = _b64url(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
    p = _b64url(json.dumps({"sub":user_id,"email":email,"exp":int(time.time())+604800}).encode())
    s = _b64url(hmac.new(SECRET_KEY.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{s}"

def verify_token(token):
    try:
        h, p, s = token.split(".")
        exp = _b64url(hmac.new(SECRET_KEY.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, exp): raise ValueError("bad sig")
        data = json.loads(_unb64url(p))
        if data["exp"] < int(time.time()): raise ValueError("expired")
        return data
    except: raise HTTPException(401, "Invalid or expired token")

bearer = HTTPBearer(auto_error=False)
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if not creds: raise HTTPException(401, "Not authenticated")
    return verify_token(creds.credentials)

# ════════════════════════════════════════════════════════════
# MODELS
# ════════════════════════════════════════════════════════════
class SignupRequest(BaseModel):
    name: str; email: str; password: str

class LoginRequest(BaseModel):
    email: str; password: str

class IdeaRequest(BaseModel):
    idea: str; context: str = ""

class SubscribeRequest(BaseModel):
    plan: str

# ════════════════════════════════════════════════════════════
# AUTH ROUTES
# ════════════════════════════════════════════════════════════
@app.post("/auth/signup")
def signup(req: SignupRequest):
    if len(req.password) < 6: raise HTTPException(400, "Password must be at least 6 characters")
    if len(req.name.strip()) < 2: raise HTTPException(400, "Name must be at least 2 characters")
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (email,name,password_hash,created_at) VALUES (?,?,?,?)",
            (req.email.lower().strip(), req.name.strip(), hash_password(req.password), datetime.utcnow().isoformat()))
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email=?", (req.email.lower().strip(),)).fetchone()
        token = create_token(row["id"], req.email.lower().strip())
        return {"token": token, "name": req.name.strip(), "email": req.email.lower().strip()}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Email already registered")
    finally: conn.close()

@app.post("/auth/login")
def login(req: LoginRequest):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (req.email.lower().strip(),)).fetchone()
        if not row or not verify_password(req.password, row["password_hash"]):
            raise HTTPException(401, "Invalid email or password")
        token = create_token(row["id"], row["email"])
        return {"token": token, "name": row["name"], "email": row["email"]}
    finally: conn.close()

@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    conn = get_db()
    try:
        row = conn.execute("SELECT name,email,created_at,plan FROM users WHERE id=?", (user["sub"],)).fetchone()
        if not row: raise HTTPException(404, "User not found")
        return {"name": row["name"], "email": row["email"], "created_at": row["created_at"], "plan": row["plan"] or "free"}
    finally: conn.close()

# ════════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ════════════════════════════════════════════════════════════
@app.get("/auth/google")
async def google_login():
    from urllib.parse import urlencode
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))

@app.get("/auth/google/callback")
async def google_callback(code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}?error=google_cancelled")
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                }
            )
            tokens = token_resp.json()
            if "error" in tokens:
                return RedirectResponse(f"{FRONTEND_URL}?error=token_exchange_failed")

            # Get user info
            user_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            user_info = user_resp.json()

        email     = user_info.get("email", "").lower()
        name      = user_info.get("name", email.split("@")[0])
        google_id = user_info.get("id", "")

        if not email:
            return RedirectResponse(f"{FRONTEND_URL}?error=no_email")

        conn = get_db()
        try:
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (email,name,password_hash,created_at,google_id) VALUES (?,?,?,?,?)",
                    (email, name, "google_oauth_user", datetime.utcnow().isoformat(), google_id)
                )
                conn.commit()
                row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            else:
                conn.execute("UPDATE users SET google_id=? WHERE email=?", (google_id, email))
                conn.commit()
            token = create_token(row["id"], email)
        finally:
            conn.close()

        from urllib.parse import quote
        return RedirectResponse(
            f"{FRONTEND_URL}?token={token}&name={quote(name)}&email={quote(email)}"
        )
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}?error={str(e)[:50]}")

# ════════════════════════════════════════════════════════════
# PADDLE PAYMENT
# ════════════════════════════════════════════════════════════
PADDLE_API_KEY    = os.getenv("PADDLE_API_KEY")
PADDLE_CLIENT_TOKEN = os.getenv("PADDLE_CLIENT_TOKEN")
PLANS = {
    "starter_monthly": os.getenv("PADDLE_STARTER_MONTHLY", "pri_01ksaa2vys2vsp13zy9k5v1a27"),
    "starter_yearly":  os.getenv("PADDLE_STARTER_YEARLY",  "pri_01ksaac3tz9tene628fvrn22gr"),
    "pro_monthly":     os.getenv("PADDLE_PRO_MONTHLY",     "pri_01ksahee4yvc0peh8az14a24sm"),
    "pro_yearly":      os.getenv("PADDLE_PRO_YEARLY",      "pri_01ksahmxrvrwd10ks9bd83m7za"),
}

@app.post("/paddle/subscribe")
async def paddle_subscribe(req: SubscribeRequest, user=Depends(get_current_user)):
    price_id = PLANS.get(req.plan)
    if not price_id: raise HTTPException(400, "Invalid plan")
    conn = get_db()
    try:
        row = conn.execute("SELECT name,email FROM users WHERE id=?", (user["sub"],)).fetchone()
        if not row: raise HTTPException(404, "User not found")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.paddle.com/transactions",
                headers={"Authorization": f"Bearer {PADDLE_API_KEY}", "Content-Type": "application/json"},
                json={"items": [{"price_id": price_id, "quantity": 1}], "customer": {"email": row["email"]}}
            )
            data = resp.json()
            if resp.status_code != 201:
                raise HTTPException(400, data.get("error", {}).get("detail", "Payment error"))
            return {"checkout_url": data.get("data", {}).get("checkout", {}).get("url")}
    finally: conn.close()

@app.post("/paddle/webhook")
async def paddle_webhook(request: Request):
    payload = await request.json()
    if payload.get("event_type") == "subscription.activated":
        email   = payload.get("data", {}).get("customer", {}).get("email")
        plan_id = payload.get("data", {}).get("items", [{}])[0].get("price", {}).get("id", "")
        plan    = "starter" if plan_id in [PLANS["starter_monthly"], PLANS["starter_yearly"]] else "pro" if plan_id in [PLANS["pro_monthly"], PLANS["pro_yearly"]] else "free"
        conn = get_db()
        try:
            conn.execute("UPDATE users SET plan=? WHERE email=?", (plan, email))
            conn.commit()
        finally: conn.close()
    return {"status": "ok"}

@app.get("/paddle/my-plan")
async def my_plan(user=Depends(get_current_user)):
    conn = get_db()
    try:
        row = conn.execute("SELECT plan FROM users WHERE id=?", (user["sub"],)).fetchone()
        return {"plan": row["plan"] if row and row["plan"] else "free"}
    finally: conn.close()

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
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
