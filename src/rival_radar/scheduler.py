import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from rival_radar.database import SessionLocal, init_db
from rival_radar.models import Competitor, Run
from rival_radar.state import MonitorState

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_competitor(comp: Competitor) -> None:
    from rival_radar.graph import app  # imported here to avoid circular import at module load
    from rival_radar.tracing import build_run_config

    urls: list[str] = json.loads(comp.urls)
    state = MonitorState(
        competitors=[{"competitor_id": comp.id, "name": comp.name, "urls": urls}],
        diffs={},
        analyses=[],
        brief="",
        run_id=0,
    )
    run_config = build_run_config(run_name=f"rival-radar:{comp.name}")
    logger.info("Running pipeline for competitor: %s", comp.name)

    with SessionLocal() as db:
        run = Run(competitor_id=comp.id, status="running")
        db.add(run)
        db.commit()
        run_id = run.id

    try:
        result = app.invoke(state, config=run_config)
        with SessionLocal() as db:
            completed = db.get(Run, run_id)
            if completed:
                completed.brief = result.get("brief") or None
                completed.status = "done"
                completed.finished_at = datetime.utcnow()
                db.commit()
    except Exception:
        with SessionLocal() as db:
            failed = db.get(Run, run_id)
            if failed:
                failed.status = "failed"
                failed.finished_at = datetime.utcnow()
                db.commit()
        raise

    logger.info("Pipeline complete for competitor: %s", comp.name)


def run_competitor_by_id(competitor_id: int) -> None:
    """Load a fresh Competitor and run the pipeline. Safe to call from background tasks."""
    with SessionLocal() as db:
        comp = db.get(Competitor, competitor_id)
        if comp is None:
            logger.warning("Competitor %d not found for run", competitor_id)
            return
        run_competitor(comp)  # comp is attached and live throughout this call


def _run_by_cadence(cadence: str) -> None:
    """Run all competitors with the given cadence, concurrently."""
    init_db()
    with SessionLocal() as db:
        competitor_ids = [
            c.id for c in db.query(Competitor).filter(Competitor.cadence == cadence).all()
        ]

    if not competitor_ids:
        logger.info("No %s competitors to run.", cadence)
        return

    logger.info("Starting %s run for %d competitor(s).", cadence, len(competitor_ids))
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_competitor_by_id, cid): cid for cid in competitor_ids}
        for future in as_completed(futures):
            cid = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("Pipeline failed for competitor id: %d", cid)


@scheduler.scheduled_job("cron", day_of_week="mon", hour=9, minute=0, id="weekly_run")
def weekly_job() -> None:
    logger.info("Weekly scheduled run starting.")
    _run_by_cadence("weekly")


@scheduler.scheduled_job("cron", hour=9, minute=0, id="daily_run")
def daily_job() -> None:
    logger.info("Daily scheduled run starting.")
    _run_by_cadence("daily")


@scheduler.scheduled_job("cron", minute=0, id="hourly_run")
def hourly_job() -> None:
    logger.info("Hourly scheduled run starting.")
    _run_by_cadence("hourly")


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started — weekly Mon 09:00, daily 09:00, hourly :00.")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
