# api.py — FastAPI Backend + Authentication (with Google OAuth)
# Run: python api.py
#
# Required .env variables:
#   GROQ_API_KEY=...
#   JWT_SECRET=change-me-in-production-use-long-random-string
#   DB_PATH=users.db
#   GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
#   GOOGLE_CLIENT_SECRET=your-google-client-secret
#   FRONTEND_URL=http://localhost:8000   (used for OAuth redirect)

import os, sys, json, asyncio, sqlite3, hashlib, hmac, secrets, base64, time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv

# ── optional: install with  pip install httpx  ──────────────────────────────
try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
SECRET_KEY        = os.getenv("JWT_SECRET", "change-me-in-production-use-long-random-string")
DB_PATH           = os.getenv("DB_PATH", "users.db")
GOOGLE_CLIENT_ID  = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
FRONTEND_URL      = os.getenv("FRONTEND_URL", "http://localhost:8000")

# Google OAuth endpoints
GOOGLE_AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL  = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Redirect URI that Google will call after the user approves
GOOGLE_REDIRECT_URI = f"{FRONTEND_URL}/auth/google/callback"

from ceo_brain import CEOBrain
from marketing_agent import MarketingAgent
from finance_agent import FinanceAgent
from risk_agent import RiskAgent
from State import AgentState

app = FastAPI(title="CEO Agent SaaS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════════════
# DATABASE
# ════════════════════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # Add google_id column for Google OAuth users
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            email           TEXT UNIQUE NOT NULL,
            name            TEXT NOT NULL,
            password_hash   TEXT,           -- NULL for Google-only accounts
            google_id       TEXT UNIQUE,    -- NULL for email/password accounts
            avatar_url      TEXT,
            created_at      TEXT NOT NULL
        )
    """)
    # Migration: add columns to existing DB if they are missing
    for col, definition in [
        ("google_id",  "TEXT UNIQUE"),
        ("avatar_url", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()

init_db()

# ════════════════════════════════════════════════════════════
# PASSWORD HASHING
# ════════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":")
        new_h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(h, new_h.hex())
    except Exception:
        return False

# ════════════════════════════════════════════════════════════
# JWT  (hand-rolled HS256 — no extra library needed)
# ════════════════════════════════════════════════════════════
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64url(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)

def create_token(user_id: int, email: str) -> str:
    header  = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + 60 * 60 * 24 * 7,   # 7 days
    }).encode())
    sig = _b64url(
        hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{sig}"

def verify_token(token: str) -> dict:
    try:
        header, payload, sig = token.split(".")
        expected = _b64url(
            hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
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
# AUTH ROUTES — Email / Password
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
             hash_password(req.password), datetime.utcnow().isoformat()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (req.email.lower().strip(),)
        ).fetchone()
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
        if not row:
            raise HTTPException(401, "Invalid email or password")
        # Google-only accounts have no password_hash
        if not row["password_hash"]:
            raise HTTPException(400, "This account uses Google Sign-In. Please login with Google.")
        if not verify_password(req.password, row["password_hash"]):
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
            "SELECT name, email, avatar_url, created_at FROM users WHERE id = ?", (user["sub"],)
        ).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return {
            "name": row["name"],
            "email": row["email"],
            "avatar_url": row["avatar_url"],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()

# ════════════════════════════════════════════════════════════
# AUTH ROUTES — Google OAuth 2.0
# ════════════════════════════════════════════════════════════

@app.get("/auth/google")
def google_login():
    """
    Step 1 — Redirect the browser to Google's consent screen.
    The frontend should open this URL in the same tab:
        window.location.href = "/auth/google"
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth is not configured. Set GOOGLE_CLIENT_ID in .env")
    if not _HTTPX_AVAILABLE:
        raise HTTPException(500, "httpx is required for Google OAuth. Run: pip install httpx")

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
        "prompt":        "select_account",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}")


@app.get("/auth/google/callback")
async def google_callback(code: str = None, error: str = None):
    """
    Step 2 — Google redirects here with ?code=... after the user approves.
    We exchange the code for tokens, fetch the user profile, upsert the DB row,
    mint our own JWT, and redirect back to the frontend with the token in the
    URL fragment so the JS can grab it:
        /#token=<jwt>&name=<name>&email=<email>
    """
    if error:
        return RedirectResponse(f"{FRONTEND_URL}/#google_error={error}")
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}/#google_error=missing_code")

    async with httpx.AsyncClient(timeout=10) as client:
        # ── Exchange authorisation code for access token ──────────────────
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
        token_data = token_resp.json()

        if "error" in token_data:
            return RedirectResponse(
                f"{FRONTEND_URL}/#google_error={token_data.get('error_description', token_data['error'])}"
            )

        access_token = token_data["access_token"]

        # ── Fetch Google user profile ──────────────────────────────────────
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo = userinfo_resp.json()

    google_id  = userinfo.get("sub")
    email      = (userinfo.get("email") or "").lower().strip()
    name       = userinfo.get("name") or email.split("@")[0]
    avatar_url = userinfo.get("picture")

    if not google_id or not email:
        return RedirectResponse(f"{FRONTEND_URL}/#google_error=could_not_fetch_profile")

    # ── Upsert user in DB ──────────────────────────────────────────────────
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id, google_id FROM users WHERE email = ?", (email,)
        ).fetchone()

        if existing:
            # Email already registered — link Google account if not linked yet
            if not existing["google_id"]:
                conn.execute(
                    "UPDATE users SET google_id = ?, avatar_url = ? WHERE id = ?",
                    (google_id, avatar_url, existing["id"]),
                )
                conn.commit()
            user_id = existing["id"]
        else:
            # Brand-new user via Google
            conn.execute(
                "INSERT INTO users (email, name, google_id, avatar_url, created_at) VALUES (?, ?, ?, ?, ?)",
                (email, name, google_id, avatar_url, datetime.utcnow().isoformat()),
            )
            conn.commit()
            user_id = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()["id"]
    finally:
        conn.close()

    jwt = create_token(user_id, email)

    # Redirect to frontend; JS reads the fragment and stores the token
    import urllib.parse
    fragment = urllib.parse.urlencode({"token": jwt, "name": name, "email": email})
    return RedirectResponse(f"{FRONTEND_URL}/#{fragment}")


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
                f"Research this business idea: {req.idea}\n"
                f"Cover: market size, target audience, top 3 competitors, opportunity.")
            state["research_output"] = r.raw
            state["ceo_direction"]   = r.recommendation or ""
            yield send("agent_done", {"agent": "Research", "output": r.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Research", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Marketing", "icon": "📣"})
        try:
            result = MarketingAgent(api_key=GROQ_API_KEY).run(
                req.idea, state["research_output"], state["ceo_direction"])
            state["marketing_output"] = result.raw
            yield send("agent_done", {"agent": "Marketing", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Marketing", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Finance", "icon": "💰"})
        try:
            result = FinanceAgent(api_key=GROQ_API_KEY).run(
                req.idea, state["research_output"], state["marketing_output"])
            state["finance_output"] = result.raw
            yield send("agent_done", {"agent": "Finance", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Finance", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "Risk", "icon": "⚠️"})
        try:
            result = RiskAgent(api_key=GROQ_API_KEY).run(
                req.idea, state["research_output"],
                state["marketing_output"], state["finance_output"])
            state["risk_output"] = result.raw
            yield send("agent_done", {"agent": "Risk", "output": result.raw})
        except Exception as e:
            yield send("agent_error", {"agent": "Risk", "error": str(e)})
        await asyncio.sleep(0.1)

        yield send("agent_start", {"agent": "CEO Decision", "icon": "👔"})
        try:
            result = CEOBrain(api_key=GROQ_API_KEY).think(
                f"Synthesise all reports into final executive decision.\nRequest: {req.idea}\n"
                f"Research:\n{state['research_output'][:500]}\n"
                f"Marketing:\n{state['marketing_output'][:500]}\n"
                f"Finance:\n{state['finance_output'][:500]}\n"
                f"Risk:\n{state['risk_output'][:500]}")
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
