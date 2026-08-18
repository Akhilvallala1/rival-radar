from rival_radar.models import UserTier

TIER_COMPETITOR_LIMIT: dict[UserTier, int | None] = {
    UserTier.starter: 2,
    UserTier.pro: 10,
    UserTier.team: None,  # unlimited
}

TIER_ALLOWED_CADENCES: dict[UserTier, frozenset[str]] = {
    UserTier.starter: frozenset({"weekly"}),
    UserTier.pro: frozenset({"weekly", "daily"}),
    UserTier.team: frozenset({"weekly", "daily", "hourly"}),
}
