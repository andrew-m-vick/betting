"""Application configuration.

Loads values from environment variables via python-dotenv. Exposes three
config classes (Development, Production, Testing) selected by FLASK_ENV.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-do-not-use-in-prod")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping handles Neon's scale-to-zero cold starts by validating
    # connections before use; a dead connection is silently replaced.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
    ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

    # Fixed list of sportsbooks we track. Keys match The Odds API bookmaker keys.
    TRACKED_SPORTSBOOKS = {
        "draftkings": "DraftKings",
        "fanduel": "FanDuel",
        "betmgm": "BetMGM",
        "caesars": "Caesars",
        "betrivers": "BetRivers",
        "pointsbetus": "PointsBet",
    }

    # Sports we cover. Keys match The Odds API sport keys.
    TRACKED_SPORTS = {
        "americanfootball_nfl": "NFL",
        "basketball_nba": "NBA",
        "baseball_mlb": "MLB",
        "icehockey_nhl": "NHL",
        "americanfootball_ncaaf": "NCAAF",
        "basketball_ncaab": "NCAAB",
        "soccer_usa_mls": "MLS",
    }

    # Markets we fetch per game.
    TRACKED_MARKETS = ("h2h", "spreads", "totals")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    # Tests use a separate DATABASE_URL if set, else fall back to the main one.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", os.environ.get("DATABASE_URL")
    )
    WTF_CSRF_ENABLED = False


_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config() -> type[Config]:
    env = os.environ.get("FLASK_ENV", "development").lower()
    return _CONFIG_MAP.get(env, DevelopmentConfig)
