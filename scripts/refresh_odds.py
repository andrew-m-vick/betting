"""Daily refresh: odds -> scores -> settle bets. Intended as a Railway cron.

Usage:
    python scripts/refresh_odds.py [--sports=nfl,nba] [--markets=h2h,spreads] [--skip-scores] [--skip-settle]

Exit codes:
    0  success
    1  configuration error (missing env, etc.)
    2  partial failure (one or more sports failed; others succeeded)
    3  rate limit exhausted mid-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import create_app
from app.extensions import db
from app.services.ingest import refresh_sport
from app.services.odds_api import OddsAPIClient, OddsAPIRateLimitError
from app.services.scores_ingest import in_season_sport_keys, ingest_scores_for_sport
from app.services.settlement import settle_pending_bets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("refresh_odds")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh odds, scores, and settle bets.")
    parser.add_argument("--sports", help="Comma-separated sport display names (nfl,nba,...).")
    parser.add_argument("--markets", default="h2h,spreads,totals", help="Markets to fetch.")
    parser.add_argument("--skip-scores", action="store_true", help="Skip the scores step.")
    parser.add_argument("--skip-settle", action="store_true", help="Skip bet settlement.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        api_key = app.config["ODDS_API_KEY"]
        if not api_key:
            logger.error("ODDS_API_KEY not configured")
            return 1

        client = OddsAPIClient(api_key, app.config["ODDS_API_BASE_URL"])
        tracked_books: dict[str, str] = app.config["TRACKED_SPORTSBOOKS"]
        tracked_sports: dict[str, str] = app.config["TRACKED_SPORTS"]

        if args.sports:
            wanted = {s.strip().lower() for s in args.sports.split(",")}
            targets = {k: v for k, v in tracked_sports.items() if v.lower() in wanted}
            if not targets:
                logger.error("no matching sports in --sports=%s", args.sports)
                return 1
        else:
            targets = tracked_sports
        markets = tuple(m.strip() for m in args.markets.split(",") if m.strip())

        failures: list[str] = []

        # -------- Step 1: odds --------
        logger.info("=== odds refresh: %d sports ===", len(targets))
        for sport_key, display in targets.items():
            try:
                result = refresh_sport(client, sport_key, display, tracked_books, markets)
                logger.info("%s: %s", display, result)
            except OddsAPIRateLimitError:
                logger.error("rate limit exhausted during odds refresh; stopping")
                db.session.commit()
                return 3
            except Exception:
                logger.exception("failed to refresh odds for %s", sport_key)
                failures.append(sport_key)
                db.session.rollback()
        db.session.commit()

        # -------- Step 2: scores (in-season sports only) --------
        if not args.skip_scores:
            in_season = in_season_sport_keys(tracked_sports)
            logger.info("=== scores refresh: %d in-season sports ===", len(in_season))
            for sport_key, display in in_season.items():
                try:
                    result = ingest_scores_for_sport(client, sport_key)
                    logger.info("%s: %s", display, result)
                except OddsAPIRateLimitError:
                    logger.error("rate limit exhausted during scores refresh; stopping")
                    db.session.commit()
                    return 3
                except Exception:
                    logger.exception("failed to fetch scores for %s", sport_key)
                    failures.append(f"{sport_key}:scores")
                    db.session.rollback()
            db.session.commit()

        # -------- Step 3: bet settlement --------
        if not args.skip_settle:
            logger.info("=== settling pending bets ===")
            result = settle_pending_bets()
            logger.info("settlement: %s", result)

        if client.last_quota:
            logger.info(
                "run complete; quota remaining=%s used=%s",
                client.last_quota.remaining, client.last_quota.used,
            )
        return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
