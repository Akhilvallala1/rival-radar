import json
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rival_radar.database import get_session, init_db
from rival_radar.models import Competitor
from rival_radar.scheduler import run_competitor, start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Rival Radar", version="0.1.0", lifespan=lifespan)


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


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "rival-radar"}


@app.post("/competitors", response_model=CompetitorOut, status_code=201)
def create_competitor(
    payload: CompetitorCreate, db: Session = Depends(get_session)
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
def list_competitors(db: Session = Depends(get_session)) -> list[CompetitorOut]:
    comps = db.query(Competitor).all()
    return [
        CompetitorOut(id=c.id, name=c.name, urls=json.loads(c.urls), cadence=c.cadence)
        for c in comps
    ]


@app.delete("/competitors/{competitor_id}", status_code=204)
def delete_competitor(competitor_id: int, db: Session = Depends(get_session)) -> None:
    comp = db.query(Competitor).filter_by(id=competitor_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    db.delete(comp)
    db.commit()


@app.post("/competitors/{competitor_id}/run")
def trigger_run(
    competitor_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
) -> dict:
    comp = db.query(Competitor).filter_by(id=competitor_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    background_tasks.add_task(run_competitor, comp)
    return {"status": "queued", "competitor_id": competitor_id, "name": comp.name}
