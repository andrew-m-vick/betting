"""SQLAlchemy models for the betting analytics platform."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)

# BigInteger autoincrement is a Postgres feature; SQLite (used in tests) needs Integer.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tracked_bets: Mapped[list["TrackedBet"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Sport(db.Model):
    __tablename__ = "sports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)

    games: Mapped[list["Game"]] = relationship(back_populates="sport")


class Sportsbook(db.Model):
    __tablename__ = "sportsbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)


class Game(db.Model):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    home_team: Mapped[str] = mapped_column(String(128), nullable=False)
    away_team: Mapped[str] = mapped_column(String(128), nullable=False)
    commence_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sport: Mapped[Sport] = relationship(back_populates="games")
    odds_snapshots: Mapped[list["OddsSnapshot"]] = relationship(back_populates="game", cascade="all, delete-orphan")


class OddsSnapshot(db.Model):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    sportsbook_id: Mapped[int] = mapped_column(ForeignKey("sportsbooks.id"), nullable=False)
    # 'h2h' | 'spreads' | 'totals' — matches The Odds API market keys.
    market_type: Mapped[str] = mapped_column(String(16), nullable=False)
    home_odds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    away_odds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # For spreads: the point spread. For totals: the over/under line. Null for h2h.
    spread_or_total: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    game: Mapped[Game] = relationship(back_populates="odds_snapshots")
    sportsbook: Mapped[Sportsbook] = relationship()

    __table_args__ = (
        Index("ix_odds_game_book_time", "game_id", "sportsbook_id", "captured_at"),
    )


class TrackedBet(db.Model):
    __tablename__ = "tracked_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # game_id nullable: parlays span multiple games and link via parlay_legs.
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"), nullable=True)
    sportsbook_id: Mapped[int] = mapped_column(ForeignKey("sportsbooks.id"), nullable=False)
    # 'moneyline' | 'spread' | 'total' | 'parlay'
    bet_type: Mapped[str] = mapped_column(String(16), nullable=False)
    selection: Mapped[str] = mapped_column(String(255), nullable=False)
    odds_at_bet: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # 'pending' | 'won' | 'lost' | 'push' | 'void'
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    payout: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tracked_bets")
    game: Mapped[Game | None] = relationship()
    sportsbook: Mapped[Sportsbook] = relationship()
    legs: Mapped[list["ParlayLeg"]] = relationship(back_populates="parlay_bet", cascade="all, delete-orphan")


class ParlayLeg(db.Model):
    __tablename__ = "parlay_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parlay_bet_id: Mapped[int] = mapped_column(ForeignKey("tracked_bets.id"), nullable=False, index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    selection: Mapped[str] = mapped_column(String(255), nullable=False)
    odds: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    parlay_bet: Mapped[TrackedBet] = relationship(back_populates="legs")
    game: Mapped[Game] = relationship()
