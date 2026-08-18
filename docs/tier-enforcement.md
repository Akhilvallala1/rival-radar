# Tier Enforcement — Design Spec

## Overview

Gate competitor count and cadence options by subscription tier to enable monetization. All enforcement lives server-side so that client UI changes alone cannot bypass limits.

---

## Pricing Tiers

| Tier    | Price     | Max Competitors | Allowed Cadences        |
|---------|-----------|-----------------|-------------------------|
| starter | Free      | 2               | `weekly`                |
| pro     | $99/mo    | 10              | `weekly`, `daily`       |
| team    | $299/mo   | Unlimited       | `weekly`, `daily`, `hourly` |

---

## 1. Model Change — `User.tier`

Add a `tier` column to the `users` table using a SQLAlchemy `Enum` type backed by a Python `enum.Enum`.

### Python `enum` definition

```python
# src/rival_radar/models.py
import enum

class UserTier(str, enum.Enum):
    starter = "starter"
    pro     = "pro"
    team    = "team"
```

### SQLAlchemy column addition to `User`

```python
from sqlalchemy import Enum as SAEnum

class User(Base):
    __tablename__ = "users"

    id:            Mapped[int]          = mapped_column(Integer, primary_key=True)
    email:         Mapped[str]          = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None]   = mapped_column(String(255))
    google_id:     Mapped[str | None]   = mapped_column(String(255), unique=True)
    name:          Mapped[str | None]   = mapped_column(String(255))
    # NEW FIELD ↓
    tier:          Mapped[UserTier]     = mapped_column(
                                             SAEnum(UserTier, name="user_tier"),
                                             default=UserTier.starter,
                                             nullable=False,
                                             server_default="starter",
                                         )
    created_at:    Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)

    competitors: Mapped[list["Competitor"]] = relationship(back_populates="owner")
```

**Migration note:** Add an Alembic migration (or equivalent `ALTER TABLE`) that adds `tier VARCHAR(10) NOT NULL DEFAULT 'starter'` to existing rows before applying the enum constraint.

---

## 2. Tier Limits Constants

Define limits in a single place so they are easy to update and test:

```python
# src/rival_radar/tiers.py

from rival_radar.models import UserTier

TIER_COMPETITOR_LIMIT: dict[UserTier, int | None] = {
    UserTier.starter: 2,
    UserTier.pro:     10,
    UserTier.team:    None,   # None == unlimited
}

TIER_ALLOWED_CADENCES: dict[UserTier, frozenset[str]] = {
    UserTier.starter: frozenset({"weekly"}),
    UserTier.pro:     frozenset({"weekly", "daily"}),
    UserTier.team:    frozenset({"weekly", "daily", "hourly"}),
}
```

---

## 3. Endpoint Logic — `POST /competitors`

The existing `create_competitor` handler in `src/rival_radar/api.py` must apply two gates before inserting the row. Admin callers (`current_user is None`) bypass all tier checks.

### Pseudocode

```
function create_competitor(payload, db, current_user):

    # 1. URL safety — already present, unchanged
    for url in payload.urls:
        validate_url_safe(url)   # raises 422 on bad URL

    # 2. Tier gates (skip for admin API-key callers)
    if current_user is not None:
        user = db.get(User, current_user)         # 404 if somehow missing
        tier = user.tier                          # UserTier enum value

        # 2a. Competitor count limit
        limit = TIER_COMPETITOR_LIMIT[tier]
        if limit is not None:
            count = db.query(Competitor)
                      .filter(Competitor.user_id == current_user)
                      .count()
            if count >= limit:
                raise HTTP 403 {
                    "error":   "tier_limit_exceeded",
                    "message": f"Your {tier.value} plan allows up to {limit} competitors. "
                               f"Upgrade to Pro or Team to add more.",
                    "current_count": count,
                    "limit":         limit,
                    "tier":          tier.value,
                }

        # 2b. Cadence check
        allowed = TIER_ALLOWED_CADENCES[tier]
        if payload.cadence not in allowed:
            raise HTTP 403 {
                "error":   "cadence_not_allowed",
                "message": f"The '{payload.cadence}' cadence is not available on the "
                           f"{tier.value} plan. Allowed cadences: {sorted(allowed)}.",
                "requested_cadence": payload.cadence,
                "allowed_cadences":  sorted(allowed),
                "tier":              tier.value,
            }

    # 3. Insert — unchanged from current implementation
    comp = Competitor(user_id=current_user, ...)
    db.add(comp); db.commit(); db.refresh(comp)
    return CompetitorOut(...)
```

---

## 4. Error Response Format

All tier errors return HTTP **403 Forbidden** with a consistent JSON body:

```json
{
  "error":   "<machine_readable_code>",
  "message": "<human_readable_explanation>",
  "<context_key>": "<context_value>"
}
```

### Example — competitor limit exceeded (Starter user, 2/2 used)

```json
HTTP 403 Forbidden
{
  "error":         "tier_limit_exceeded",
  "message":       "Your starter plan allows up to 2 competitors. Upgrade to Pro or Team to add more.",
  "current_count": 2,
  "limit":         2,
  "tier":          "starter"
}
```

### Example — cadence not allowed (Starter user requests daily)

```json
HTTP 403 Forbidden
{
  "error":             "cadence_not_allowed",
  "message":           "The 'daily' cadence is not available on the starter plan. Allowed cadences: ['weekly'].",
  "requested_cadence": "daily",
  "allowed_cadences":  ["weekly"],
  "tier":              "starter"
}
```

---

## 5. Future Considerations

- **Tier upgrades:** A `PATCH /users/me/tier` endpoint (or a Stripe webhook handler) sets `user.tier`. No other changes are needed because the gate re-reads the tier on each request.
- **Admin override:** The existing `current_user is None` admin path already bypasses all tier checks, which is the desired behavior for internal tooling.
- **UI feedback:** The dashboard's `addCompetitor()` JS function should handle the new 403 response codes and display tier-appropriate upsell messages.
