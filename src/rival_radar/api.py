import json
import secrets
from contextlib import asynccontextmanager

from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Security,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from rival_radar.config import settings
from rival_radar.database import get_session, init_db
from rival_radar.models import Competitor, Run
from rival_radar.scheduler import run_competitor, start_scheduler, stop_scheduler


# ── Rate limiter ───────────────────────────────────────────────────────────────
def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Cloud Run's LB appends the real client IP as the rightmost value;
        # leftmost values are attacker-controlled and must not be trusted.
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_ip)

# ── Auth ───────────────────────────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _valid_password(pw: str) -> bool:
    return bool(pw) and secrets.compare_digest(pw, settings.dashboard_password)


def require_auth(
    request: Request,
    api_key: str = Security(_api_key_header),
    rr_session: str = Cookie(default=""),
) -> None:
    if _valid_password(api_key) or _valid_password(rr_session):
        return
    raise HTTPException(status_code=401, detail="Unauthorized")

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Rival Radar — Sign in</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           background: #0f0f10; color: #e8e8ed; min-height: 100vh;
           display: flex; align-items: center; justify-content: center; }
    .card { background: #16161e; border: 1px solid #1e1e2a; border-radius: 16px;
            padding: 2.75rem 2.25rem; width: 360px; }
    .logo { font-size: 1.6rem; font-weight: 800; color: #fff; text-align: center;
            margin-bottom: 0.35rem; letter-spacing: -0.5px; }
    .logo span { color: #6366f1; }
    .sub { text-align: center; font-size: 0.875rem; color: #6b7280; margin-bottom: 2rem; }
    label { display: block; font-size: 0.78rem; color: #9ca3af; margin-bottom: 0.3rem; }
    input[type=password] { width: 100%; background: #0f0f10; border: 1px solid #2d2d3a;
                           border-radius: 8px; padding: 0.6rem 0.85rem; color: #e8e8ed;
                           font-size: 0.9rem; outline: none; margin-bottom: 1.25rem; }
    input[type=password]:focus { border-color: #6366f1; }
    button { width: 100%; background: #6366f1; color: #fff; border: none; border-radius: 8px;
             padding: 0.65rem; font-size: 0.9rem; font-weight: 600; cursor: pointer; }
    button:hover { background: #4f46e5; }
    .err { color: #ef4444; font-size: 0.8rem; margin-top: 0.85rem; text-align: center;
           min-height: 1.2rem; }
    .footer { text-align: center; font-size: 0.75rem; color: #374151; margin-top: 1.75rem; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Rival <span>Radar</span></div>
    <div class="sub">Competitive intelligence for B2B teams</div>
    <form method="post" action="/login">
      <label for="password">Dashboard password</label>
      <input id="password" name="password" type="password" placeholder="Enter password" autofocus required />
      <button type="submit">Sign in</button>
    </form>
    {error}
    <div class="footer">Rival Radar &copy; 2026</div>
  </div>
</body>
</html>"""

_LOGIN_HTML_OK = LOGIN_HTML.replace("{error}", '<div class="err"></div>')
_LOGIN_HTML_ERR = LOGIN_HTML.replace("{error}", '<div class="err">Incorrect password — try again.</div>')

_SESSION_TTL = 60 * 60 * 24 * 7

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Rival Radar — Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           background: #0f0f10; color: #e8e8ed; line-height: 1.6; }
    a { color: #6366f1; text-decoration: none; }

    nav { display: flex; justify-content: space-between; align-items: center;
          padding: 1rem 2rem; border-bottom: 1px solid #1e1e24; }
    .logo { font-size: 1.1rem; font-weight: 700; color: #fff; }
    .logo span { color: #6366f1; }
    nav a { font-size: 0.85rem; color: #9ca3af; margin-left: 1.5rem; }

    .layout { display: grid; grid-template-columns: 340px 1fr; gap: 1.5rem;
              max-width: 1200px; margin: 2rem auto; padding: 0 1.5rem; }

    /* ── Panel ── */
    .panel { background: #16161e; border: 1px solid #1e1e2a; border-radius: 12px; padding: 1.5rem; }
    .panel-title { font-size: 0.75rem; font-weight: 600; letter-spacing: 2px;
                   text-transform: uppercase; color: #6366f1; margin-bottom: 1.25rem; }

    /* ── Add form ── */
    .form-group { margin-bottom: 0.9rem; }
    label { display: block; font-size: 0.8rem; color: #9ca3af; margin-bottom: 0.3rem; }
    input, select { width: 100%; background: #0f0f10; border: 1px solid #2d2d3a;
                    border-radius: 6px; padding: 0.5rem 0.75rem; color: #e8e8ed;
                    font-size: 0.875rem; outline: none; }
    input:focus, select:focus { border-color: #6366f1; }
    .btn { padding: 0.55rem 1.25rem; border-radius: 6px; font-size: 0.85rem;
           font-weight: 600; cursor: pointer; border: none; }
    .btn-primary { background: #6366f1; color: #fff; width: 100%; margin-top: 0.25rem; }
    .btn-primary:hover { background: #4f46e5; }
    .btn-sm { padding: 0.3rem 0.75rem; font-size: 0.78rem; border-radius: 5px; }
    .btn-run { background: #1e1e35; color: #818cf8; border: 1px solid #2d2d4a; }
    .btn-run:hover { background: #2d2d4a; }
    .btn-del { background: transparent; color: #6b7280; border: 1px solid #2d2d3a; }
    .btn-del:hover { color: #ef4444; border-color: #ef4444; }

    /* ── Competitor list ── */
    .comp-list { margin-top: 1.5rem; display: flex; flex-direction: column; gap: 0.75rem; }
    .comp-card { background: #0f0f10; border: 1px solid #1e1e2a; border-radius: 8px;
                 padding: 0.9rem 1rem; }
    .comp-header { display: flex; justify-content: space-between; align-items: center; }
    .comp-name { font-weight: 600; font-size: 0.95rem; }
    .comp-cadence { font-size: 0.75rem; color: #6b7280; background: #1e1e2a;
                    padding: 0.15rem 0.5rem; border-radius: 9999px; }
    .comp-urls { font-size: 0.78rem; color: #6b7280; margin: 0.4rem 0 0.6rem; }
    .comp-actions { display: flex; gap: 0.5rem; }
    .empty { color: #4b5563; font-size: 0.875rem; text-align: center; padding: 2rem 0; }

    /* ── Runs panel ── */
    .run-list { display: flex; flex-direction: column; gap: 1rem; }
    .run-card { background: #0f0f10; border: 1px solid #1e1e2a; border-radius: 8px; padding: 1rem 1.25rem; }
    .run-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; }
    .run-name { font-weight: 600; font-size: 0.9rem; }
    .run-time { font-size: 0.75rem; color: #6b7280; }
    .badge-ok  { background: #14532d; color: #86efac; font-size: 0.7rem; font-weight: 600;
                 padding: 0.15rem 0.5rem; border-radius: 9999px; }
    .badge-run { background: #1e1e35; color: #818cf8; font-size: 0.7rem; font-weight: 600;
                 padding: 0.15rem 0.5rem; border-radius: 9999px; }
    .brief { font-size: 0.82rem; color: #9ca3af; white-space: pre-wrap; line-height: 1.55;
             border-left: 2px solid #2d2d4a; padding-left: 0.75rem; margin-top: 0.4rem; }
    .no-brief { font-size: 0.8rem; color: #4b5563; font-style: italic; }

    .toast { position: fixed; bottom: 1.5rem; right: 1.5rem; background: #1e1e35;
             border: 1px solid #6366f1; color: #a5b4fc; padding: 0.6rem 1.1rem;
             border-radius: 8px; font-size: 0.85rem; opacity: 0; transition: opacity 0.3s;
             pointer-events: none; }
    .toast.show { opacity: 1; }

  </style>
</head>
<body>

<nav>
  <div class="logo">Rival <span>Radar</span></div>
  <div>
    <a href="/docs">API Docs</a>
    <a href="/health">Health</a>
    <a href="https://github.com/Akhilvallala1/rival-radar">GitHub</a>
    <a href="/logout" style="color:#ef4444;margin-left:1.5rem">Sign out</a>
  </div>
</nav>

<div class="layout">

  <!-- Left: add + list -->
  <div>
    <div class="panel">
      <div class="panel-title">Add Competitor</div>
      <div class="form-group">
        <label>Name</label>
        <input id="inp-name" placeholder="Acme Corp" />
      </div>
      <div class="form-group">
        <label>URLs (one per line)</label>
        <input id="inp-urls" placeholder="https://acme.com/pricing" />
      </div>
      <div class="form-group">
        <label>Cadence</label>
        <select id="inp-cadence">
          <option value="weekly">Weekly</option>
          <option value="daily">Daily</option>
          <option value="hourly">Hourly</option>
        </select>
      </div>
      <button class="btn btn-primary" onclick="addCompetitor()">Add Competitor</button>
    </div>

    <div class="comp-list" id="comp-list">
      <div class="empty">Loading...</div>
    </div>
  </div>

  <!-- Right: runs -->
  <div class="panel">
    <div class="panel-title">Recent Runs &amp; Briefs</div>
    <div class="run-list" id="run-list">
      <div class="empty">No runs yet — add a competitor and click Run Now.</div>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
// ── Utils ─────────────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                  .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

function timeAgo(iso) {
  if (!iso) return '';
  const diff = Math.floor((Date.now() - new Date(iso + 'Z')) / 1000);
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

const api = (url, opts = {}) => fetch(url, {credentials: 'same-origin', ...opts});

function handleUnauth(res) {
  if (res.status === 401) { window.location.href = '/login'; return true; }
  return false;
}

// ── Data ──────────────────────────────────────────────────────────────────────
async function loadCompetitors() {
  const res = await api('/competitors');
  if (handleUnauth(res)) return;
  const data = await res.json();
  const el = document.getElementById('comp-list');
  if (!data.length) { el.innerHTML = '<div class="empty">No competitors yet.</div>'; return; }
  el.innerHTML = data.map(c => `
    <div class="comp-card">
      <div class="comp-header">
        <span class="comp-name">${escapeHtml(c.name)}</span>
        <span class="comp-cadence">${escapeHtml(c.cadence)}</span>
      </div>
      <div class="comp-urls">${c.urls.map(escapeHtml).join('<br>')}</div>
      <div class="comp-actions">
        <button class="btn btn-sm btn-run" data-id="${c.id}" data-name="${escapeHtml(c.name)}" onclick="runNow(this.dataset.id, this.dataset.name)">&#9654; Run Now</button>
        <button class="btn btn-sm btn-del" onclick="deleteComp(${c.id})">Delete</button>
      </div>
    </div>`).join('');
}

async function loadRuns() {
  const res = await api('/runs');
  if (handleUnauth(res)) return;
  const data = await res.json();
  const el = document.getElementById('run-list');
  if (!data.length) { el.innerHTML = '<div class="empty">No runs yet — add a competitor and click Run Now.</div>'; return; }
  el.innerHTML = data.map(r => `
    <div class="run-card">
      <div class="run-meta">
        <span class="run-name">${escapeHtml(r.competitor_name)}</span>
        <div style="display:flex;gap:0.5rem;align-items:center">
          <span class="${r.status === 'done' ? 'badge-ok' : 'badge-run'}">${escapeHtml(r.status)}</span>
          <span class="run-time">${timeAgo(r.started_at)}</span>
        </div>
      </div>
      ${r.brief
        ? `<div class="brief">${escapeHtml(r.brief)}</div>`
        : `<div class="no-brief">No brief yet — run in progress or no changes detected.</div>`}
    </div>`).join('');
}

async function addCompetitor() {
  const name = document.getElementById('inp-name').value.trim();
  const urls = document.getElementById('inp-urls').value.trim().split(/\\s+/).filter(Boolean);
  const cadence = document.getElementById('inp-cadence').value;
  if (!name || !urls.length) { toast('Name and at least one URL required'); return; }
  const res = await api('/competitors', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, urls, cadence})
  });
  if (handleUnauth(res)) return;
  if (!res.ok) { toast('Failed to add competitor'); return; }
  document.getElementById('inp-name').value = '';
  document.getElementById('inp-urls').value = '';
  toast('Competitor added!');
  loadCompetitors();
}

async function deleteComp(id) {
  const res = await api('/competitors/' + id, {method: 'DELETE'});
  if (handleUnauth(res)) return;
  if (!res.ok) { toast('Failed to delete'); return; }
  toast('Deleted');
  loadCompetitors();
}

async function runNow(id, name) {
  const res = await api('/competitors/' + id + '/run', {method: 'POST'});
  if (res.status === 429) { toast('Rate limit hit — max 5 runs/hour'); return; }
  toast('Running ' + name + '...');
  setTimeout(loadRuns, 2000);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
loadCompetitors();
loadRuns();
setInterval(() => { loadCompetitors(); loadRuns(); }, 15000);
</script>
</body>
</html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Rival Radar", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# ── Schemas ────────────────────────────────────────────────────────────────────

class CompetitorCreate(BaseModel):
    name: str
    urls: list[str]
    slack_webhook: str | None = None
    cadence: str = "weekly"


class CompetitorOut(BaseModel):
    id: int
    name: str
    urls: list[str]
    cadence: str

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: int
    competitor_name: str
    started_at: str
    status: str
    brief: str | None

    model_config = {"from_attributes": True}


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(error: int = 0) -> HTMLResponse:
    return HTMLResponse(_LOGIN_HTML_ERR if error else _LOGIN_HTML_OK)


@app.post("/login", include_in_schema=False)
@limiter.limit("10/minute")
def do_login(request: Request, password: str = Form(...)) -> RedirectResponse:
    if not _valid_password(password):
        return RedirectResponse(url="/login?error=1", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("rr_session", password, httponly=True, samesite="lax", secure=True, max_age=_SESSION_TTL)
    return response


@app.get("/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("rr_session")
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False, response_model=None)
def dashboard(rr_session: str = Cookie(default="")) -> HTMLResponse | RedirectResponse:
    if not _valid_password(rr_session):
        return RedirectResponse(url="/login", status_code=302)
    return HTMLResponse(DASHBOARD_HTML, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "rival-radar"}


@app.post("/competitors", response_model=CompetitorOut, status_code=201)
@limiter.limit("20/hour")
def create_competitor(
    request: Request,
    payload: CompetitorCreate,
    db: Session = Depends(get_session),
    _: None = Depends(require_auth),
) -> CompetitorOut:
    comp = Competitor(
        name=payload.name,
        urls=json.dumps(payload.urls),
        slack_webhook=payload.slack_webhook,
        cadence=payload.cadence,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return CompetitorOut(id=comp.id, name=comp.name, urls=payload.urls, cadence=comp.cadence)


@app.get("/competitors", response_model=list[CompetitorOut])
@limiter.limit("60/minute")
def list_competitors(
    request: Request,
    db: Session = Depends(get_session),
    _: None = Depends(require_auth),
) -> list[CompetitorOut]:
    comps = db.query(Competitor).all()
    return [
        CompetitorOut(id=c.id, name=c.name, urls=json.loads(c.urls), cadence=c.cadence)
        for c in comps
    ]


@app.delete("/competitors/{competitor_id}", status_code=204)
@limiter.limit("20/hour")
def delete_competitor(
    request: Request,
    competitor_id: int,
    db: Session = Depends(get_session),
    _: None = Depends(require_auth),
) -> None:
    comp = db.query(Competitor).filter_by(id=competitor_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    db.delete(comp)
    db.commit()


@app.post("/competitors/{competitor_id}/run")
@limiter.limit("5/hour")
def trigger_run(
    request: Request,
    competitor_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
    _: None = Depends(require_auth),
) -> dict:
    comp = db.query(Competitor).filter_by(id=competitor_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    background_tasks.add_task(run_competitor, comp)
    return {"status": "queued", "competitor_id": competitor_id, "name": comp.name}


@app.get("/runs", response_model=list[RunOut])
@limiter.limit("60/minute")
def list_runs(
    request: Request,
    limit: int = 20,
    db: Session = Depends(get_session),
    _: None = Depends(require_auth),
) -> list[RunOut]:
    runs = (
        db.query(Run)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        RunOut(
            id=r.id,
            competitor_name=r.competitor.name,
            started_at=r.started_at.isoformat(),
            status=r.status,
            brief=r.brief,
        )
        for r in runs
    ]
