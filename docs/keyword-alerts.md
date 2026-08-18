# Keyword Alerts — Design Spec

## Overview

Allow users to register keyword strings against a specific competitor. Whenever the scraper detects a change whose `new_excerpt` contains any of those keywords, an immediate Slack notification is sent — without waiting for the scheduled weekly brief.

---

## 1. New Model — `CompetitorAlert`

Add a `competitor_alerts` table. Each row represents one keyword watch for one competitor, owned by one user.

### Model definition

```python
# src/rival_radar/models.py  (add below the Run class)

class CompetitorAlert(Base):
    __tablename__ = "competitor_alerts"

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int]      = mapped_column(
                                          ForeignKey("competitors.id", ondelete="CASCADE"),
                                          nullable=False,
                                          index=True,
                                      )
    user_id:       Mapped[int]      = mapped_column(
                                          ForeignKey("users.id", ondelete="CASCADE"),
                                          nullable=False,
                                          index=True,
                                      )
    keyword:       Mapped[str]      = mapped_column(String(255), nullable=False)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    competitor: Mapped["Competitor"] = relationship(back_populates="alerts")
    owner:      Mapped["User"]       = relationship(back_populates="alerts")
```

**Back-references to add:**

```python
# On Competitor — add to existing relationship list:
alerts: Mapped[list["CompetitorAlert"]] = relationship(
    back_populates="competitor", cascade="all, delete-orphan"
)

# On User — add to existing relationship list:
alerts: Mapped[list["CompetitorAlert"]] = relationship(back_populates="owner")
```

**Unique constraint:** Add `UniqueConstraint("competitor_id", "user_id", "keyword", name="uq_alert_comp_user_kw")` to `__table_args__` to prevent duplicate keyword registrations for the same competitor/user pair.

**Migration note:** Create the table with `CREATE TABLE competitor_alerts (...)` including the unique index and both FK cascade-delete clauses.

---

## 2. Pydantic Schemas

```python
# src/rival_radar/api.py  (add to the Schemas section)

class AlertCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=255)


class AlertOut(BaseModel):
    id:            int
    competitor_id: int
    keyword:       str
    created_at:    str

    model_config = {"from_attributes": True}
```

---

## 3. API Endpoints

### 3a. `POST /competitors/{id}/alerts` — Register a keyword alert

```
POST /competitors/{competitor_id}/alerts
Authorization: session cookie or X-API-Key header

Request body (JSON):
{
  "keyword": "pricing"
}

Success response — 201 Created:
{
  "id":            42,
  "competitor_id": 7,
  "keyword":       "pricing",
  "created_at":    "2026-08-18T12:00:00"
}

Error responses:
  404  — competitor not found or not owned by current user
  409  — keyword already registered for this competitor
  422  — keyword empty or exceeds 255 characters
```

**Implementation sketch:**

```python
@app.post("/competitors/{competitor_id}/alerts",
          response_model=AlertOut, status_code=201)
@limiter.limit("60/hour")
def create_alert(
    request: Request,
    competitor_id: int,
    payload: AlertCreate,
    db: Session = Depends(get_session),
    current_user: int | None = Depends(require_auth),
) -> AlertOut:
    # Ownership check — same pattern used by delete_competitor
    q = db.query(Competitor).filter(Competitor.id == competitor_id)
    if current_user is not None:
        q = q.filter(Competitor.user_id == current_user)
    comp = q.first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    # Duplicate check
    existing = (
        db.query(CompetitorAlert)
          .filter_by(competitor_id=competitor_id,
                     user_id=current_user,
                     keyword=payload.keyword.lower())
          .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Keyword already registered")

    alert = CompetitorAlert(
        competitor_id=competitor_id,
        user_id=current_user,
        keyword=payload.keyword.lower(),  # normalise to lowercase for matching
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return AlertOut(
        id=alert.id,
        competitor_id=alert.competitor_id,
        keyword=alert.keyword,
        created_at=alert.created_at.isoformat(),
    )
```

---

### 3b. `GET /competitors/{id}/alerts` — List keyword alerts for a competitor

```
GET /competitors/{competitor_id}/alerts
Authorization: session cookie or X-API-Key header

Success response — 200 OK:
[
  { "id": 42, "competitor_id": 7, "keyword": "pricing", "created_at": "2026-08-18T12:00:00" },
  { "id": 43, "competitor_id": 7, "keyword": "enterprise", "created_at": "2026-08-18T12:05:00" }
]

Error responses:
  404  — competitor not found or not owned by current user
```

**Implementation sketch:**

```python
@app.get("/competitors/{competitor_id}/alerts",
         response_model=list[AlertOut])
@limiter.limit("60/minute")
def list_alerts(
    request: Request,
    competitor_id: int,
    db: Session = Depends(get_session),
    current_user: int | None = Depends(require_auth),
) -> list[AlertOut]:
    q = db.query(Competitor).filter(Competitor.id == competitor_id)
    if current_user is not None:
        q = q.filter(Competitor.user_id == current_user)
    if not q.first():
        raise HTTPException(status_code=404, detail="Competitor not found")

    alerts = (
        db.query(CompetitorAlert)
          .filter_by(competitor_id=competitor_id, user_id=current_user)
          .order_by(CompetitorAlert.created_at.asc())
          .all()
    )
    return [
        AlertOut(
            id=a.id,
            competitor_id=a.competitor_id,
            keyword=a.keyword,
            created_at=a.created_at.isoformat(),
        )
        for a in alerts
    ]
```

---

### 3c. `DELETE /alerts/{id}` — Remove a keyword alert

```
DELETE /alerts/{alert_id}
Authorization: session cookie or X-API-Key header

Success response — 204 No Content  (empty body)

Error responses:
  404  — alert not found or not owned by current user
```

**Implementation sketch:**

```python
@app.delete("/alerts/{alert_id}", status_code=204)
@limiter.limit("60/hour")
def delete_alert(
    request: Request,
    alert_id: int,
    db: Session = Depends(get_session),
    current_user: int | None = Depends(require_auth),
) -> None:
    q = db.query(CompetitorAlert).filter(CompetitorAlert.id == alert_id)
    if current_user is not None:
        q = q.filter(CompetitorAlert.user_id == current_user)
    alert = q.first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete(alert)
    db.commit()
```

---

## 4. Pipeline Hook — Keyword Check in the Analyst Node

The keyword check runs **inside `analyst()`** in `src/rival_radar/nodes/analyst.py`, immediately after diffs are grouped by competitor and before the LLM is invoked. This placement ensures:

1. The check sees every changed excerpt that the LLM will see.
2. Immediate Slack pings go out before the weekly brief is assembled, so they are never delayed by the writer/notifier stages.

### Exact location in the pipeline

```
analyst.py  ──  analyst()
    │
    ├── group diffs by competitor          ← existing code
    │
    ├── *** KEYWORD CHECK HOOK (new) ***
    │       load alerts for all competitors in this run
    │       for each changed diff:
    │           for each alert whose competitor_id matches:
    │               if alert.keyword in new_excerpt.lower():
    │                   send_immediate_slack_alert(...)
    │
    └── invoke LLM per competitor          ← existing code
```

### Implementation

```python
# src/rival_radar/nodes/analyst.py  (additions)

from rival_radar.database import SessionLocal
from rival_radar.models import CompetitorAlert
from rival_radar.config import settings
from slack_sdk.webhook import WebhookClient


def _send_keyword_alert(
    keyword: str,
    competitor_name: str,
    url: str,
    new_excerpt: str,
    webhook_url: str,
) -> None:
    """Fire an immediate Slack message when a keyword match is found."""
    client = WebhookClient(webhook_url)
    text = (
        f":rotating_light: *Keyword alert* — `{keyword}` detected for *{competitor_name}*\n"
        f"URL: {url}\n"
        f"Excerpt: _{new_excerpt[:300]}_"
    )
    response = client.send(text=text)
    if response.status_code != 200:
        print(f"[analyst] Keyword alert Slack send failed: {response.status_code}")


def _check_keyword_alerts(
    diffs: dict,          # url → DiffEntry
    competitor_map: dict, # competitor_name → competitor_id (built from state["competitors"])
) -> None:
    """
    Load CompetitorAlert rows for every competitor in this run and send
    immediate Slack pings for any keyword found in a changed excerpt.
    Runs synchronously; Slack latency is acceptable here (~200 ms).
    """
    if not settings.slack_webhook_url:
        return

    webhook_url = settings.slack_webhook_url

    # Collect competitor IDs that have changed diffs
    changed_comp_ids = {
        competitor_map[diff["competitor"]]
        for diff in diffs.values()
        if diff.get("changed") and diff["competitor"] in competitor_map
    }
    if not changed_comp_ids:
        return

    with SessionLocal() as db:
        alerts = (
            db.query(CompetitorAlert)
              .filter(CompetitorAlert.competitor_id.in_(changed_comp_ids))
              .all()
        )

    if not alerts:
        return

    # Group alerts by competitor_id for O(1) lookup per diff
    alerts_by_comp: dict[int, list[CompetitorAlert]] = defaultdict(list)
    for a in alerts:
        alerts_by_comp[a.competitor_id].append(a)

    for url, diff in diffs.items():
        if not diff.get("changed"):
            continue
        comp_name = diff["competitor"]
        comp_id   = competitor_map.get(comp_name)
        if comp_id is None:
            continue
        new_excerpt = diff.get("new_excerpt", "").lower()
        for alert in alerts_by_comp.get(comp_id, []):
            if alert.keyword in new_excerpt:
                _send_keyword_alert(
                    keyword=alert.keyword,
                    competitor_name=comp_name,
                    url=url,
                    new_excerpt=diff.get("new_excerpt", ""),
                    webhook_url=webhook_url,
                )
```

### Updated `analyst()` function signature (showing hook insertion point)

```python
def analyst(state: MonitorState) -> dict:
    diffs = state.get("diffs", {})

    # Build a name→id map from the competitors list in state
    competitor_map = {
        c["name"]: c["competitor_id"]
        for c in state.get("competitors", [])
    }

    # *** KEYWORD CHECK — fires immediate Slack alerts before LLM work ***
    _check_keyword_alerts(diffs, competitor_map)

    # --- existing grouping + LLM invocation below, unchanged ---
    by_competitor: dict[str, list[dict]] = defaultdict(list)
    for url, diff in diffs.items():
        if diff.get("changed"):
            by_competitor[diff["competitor"]].append(...)
    ...
```

---

## 5. Implementation Checklist

- [ ] Add `CompetitorAlert` model to `src/rival_radar/models.py` with FK cascade and unique constraint
- [ ] Add back-references (`alerts`) to `Competitor` and `User` models
- [ ] Add `AlertCreate` and `AlertOut` Pydantic schemas to `src/rival_radar/api.py`
- [ ] Implement `POST /competitors/{id}/alerts` endpoint
- [ ] Implement `GET /competitors/{id}/alerts` endpoint
- [ ] Implement `DELETE /alerts/{id}` endpoint
- [ ] Add `_check_keyword_alerts()` and `_send_keyword_alert()` helpers to `src/rival_radar/nodes/analyst.py`
- [ ] Call `_check_keyword_alerts()` at the top of `analyst()`, before LLM invocations
- [ ] Write an Alembic migration (or raw SQL) to create `competitor_alerts` table
- [ ] Add keyword alert management to the dashboard UI (stretch goal)
