"""Read-side queries used by Live Odds and Arbitrage Finder.

Keeping the "latest snapshot per (game, sportsbook, market_type)" query in
one place so both pages (and future Week 3 features) use an identical
definition of "current odds."
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Game, OddsSnapshot, Sport, Sportsbook

STALE_CUTOFF = timedelta(hours=24)


def latest_snapshots_for_upcoming(
    sport_ids: list[int] | None = None,
    sportsbook_ids: list[int] | None = None,
    market_types: tuple[str, ...] = ("h2h", "spreads", "totals"),
    start_after: datetime | None = None,
    start_before: datetime | None = None,
) -> list[OddsSnapshot]:
    """Return the newest snapshot per (game, sportsbook, market_type) for
    games that haven't started yet and whose snapshots aren't stale.

    Implementation note: uses a self-join on a max(captured_at) groupby
    subquery, which works on both Postgres (production) and SQLite (tests)
    without dialect-specific features like DISTINCT ON.
    """
    now = datetime.now(timezone.utc)
    start_after = start_after or now
    fresh_cutoff = now - STALE_CUTOFF

    latest = (
        select(
            OddsSnapshot.game_id.label("game_id"),
            OddsSnapshot.sportsbook_id.label("sportsbook_id"),
            OddsSnapshot.market_type.label("market_type"),
            func.max(OddsSnapshot.captured_at).label("max_captured"),
        )
        .where(
            OddsSnapshot.market_type.in_(market_types),
            OddsSnapshot.captured_at >= fresh_cutoff,
        )
        .group_by(
            OddsSnapshot.game_id,
            OddsSnapshot.sportsbook_id,
            OddsSnapshot.market_type,
        )
        .subquery()
    )

    stmt = (
        select(OddsSnapshot)
        .join(
            latest,
            and_(
                OddsSnapshot.game_id == latest.c.game_id,
                OddsSnapshot.sportsbook_id == latest.c.sportsbook_id,
                OddsSnapshot.market_type == latest.c.market_type,
                OddsSnapshot.captured_at == latest.c.max_captured,
            ),
        )
        .join(Game, Game.id == OddsSnapshot.game_id)
        .where(Game.commence_time >= start_after, Game.completed.is_(False))
        .options(
            joinedload(OddsSnapshot.sportsbook),
            joinedload(OddsSnapshot.game).joinedload(Game.sport),
        )
    )
    if start_before is not None:
        stmt = stmt.where(Game.commence_time <= start_before)
    if sport_ids:
        stmt = stmt.where(Game.sport_id.in_(sport_ids))
    if sportsbook_ids:
        stmt = stmt.where(OddsSnapshot.sportsbook_id.in_(sportsbook_ids))

    return db.session.execute(stmt).unique().scalars().all()


def games_with_snapshot_history(min_snapshots: int = 2) -> list[Game]:
    """Games that have at least `min_snapshots` odds_snapshots — i.e. have
    actual line movement data to display."""
    subq = (
        select(OddsSnapshot.game_id, func.count(OddsSnapshot.id).label("n"))
        .group_by(OddsSnapshot.game_id)
        .having(func.count(OddsSnapshot.id) >= min_snapshots)
        .subquery()
    )
    return (
        db.session.execute(
            select(Game)
            .join(subq, subq.c.game_id == Game.id)
            .join(Sport, Sport.id == Game.sport_id)
            .order_by(Game.commence_time.desc())
            .options(joinedload(Game.sport))
        )
        .scalars()
        .all()
    )


def all_snapshots_for_game(game_id: int) -> list[OddsSnapshot]:
    return (
        db.session.execute(
            select(OddsSnapshot)
            .where(OddsSnapshot.game_id == game_id)
            .order_by(OddsSnapshot.captured_at.asc())
            .options(joinedload(OddsSnapshot.sportsbook))
        )
        .scalars()
        .all()
    )


def all_sports() -> list[Sport]:
    return db.session.execute(select(Sport).order_by(Sport.display_name)).scalars().all()


def all_sportsbooks() -> list[Sportsbook]:
    return db.session.execute(
        select(Sportsbook).order_by(Sportsbook.display_name)
    ).scalars().all()
