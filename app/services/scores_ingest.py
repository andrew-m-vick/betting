"""Ingest scores for completed games; also decides which sports are in-season.

Quota note: The Odds API's `/scores` endpoint costs ~1 credit/call, so
calling all 7 sports daily adds ~210/month on top of the odds refresh.
To keep the free tier headroom, we only call scores for sports that have
at least one event recorded in the last 3 days — a cheap proxy for
"in season."
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from ..extensions import db
from ..models import Game, Sport
from .odds_api import OddsAPIClient, parse_commence_time

logger = logging.getLogger(__name__)

IN_SEASON_WINDOW = timedelta(days=3)


def in_season_sport_keys(all_tracked: dict[str, str]) -> dict[str, str]:
    """Return tracked sports with a game commencing in the last 3 days."""
    cutoff = datetime.now(timezone.utc) - IN_SEASON_WINDOW
    active_sport_ids = set(
        db.session.execute(
            select(Game.sport_id)
            .where(Game.commence_time >= cutoff)
            .distinct()
        ).scalars()
    )
    if not active_sport_ids:
        return {}
    sport_keys_by_id = {
        row.id: row.key
        for row in db.session.execute(select(Sport)).scalars()
    }
    return {
        key: display
        for key, display in all_tracked.items()
        if any(sport_keys_by_id.get(sid) == key for sid in active_sport_ids)
    }


def ingest_scores_for_sport(
    client: OddsAPIClient, sport_key: str, days_from: int = 3
) -> dict[str, int]:
    """Update Game rows with final scores for completed events."""
    events = client.get_scores(sport_key, days_from=days_from)
    updated = 0
    for event in events:
        # Only act on completed games with scores present.
        if not event.get("completed"):
            continue
        scores = event.get("scores") or []
        if not scores:
            continue
        external_id = event["id"]
        game = db.session.execute(
            select(Game).where(Game.external_id == external_id)
        ).scalar_one_or_none()
        if game is None:
            # Score came in for a game we never ingested odds for — skip.
            continue
        score_by_team = {s["name"]: int(s["score"]) for s in scores if "score" in s and s.get("score") is not None}
        game.home_score = score_by_team.get(game.home_team)
        game.away_score = score_by_team.get(game.away_team)
        game.completed = True
        if "commence_time" in event:
            game.commence_time = parse_commence_time(event["commence_time"])
        updated += 1
    logger.info(
        "scores sport=%s events=%d completed_updated=%d", sport_key, len(events), updated
    )
    return {"events": len(events), "updated": updated}
