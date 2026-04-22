"""My Bets blueprint — auth-gated bet tracking + analytics.

Bets are logged against the catalog of Games / Sportsbooks the platform
already ingests. Settlement runs in the daily cron (see services/settlement.py).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Game, ParlayLeg, Sport, Sportsbook, TrackedBet
from ..services.math_utils import american_to_decimal
from ..services.queries import all_snapshots_for_game, latest_snapshots_for_upcoming

bets_bp = Blueprint("bets", __name__, template_folder="../templates/bets")

ALLOWED_BET_TYPES = {"moneyline", "spread", "total"}
ALLOWED_SIDES = {"moneyline": {"home", "away"}, "spread": {"home", "away"}, "total": {"over", "under"}}


def _parse_decimal(raw: str | None, field: str) -> Decimal:
    try:
        return Decimal(str(raw)) if raw not in (None, "") else Decimal("0")
    except InvalidOperation:
        raise ValueError(f"invalid {field}")


def _upcoming_games_with_books():
    snaps = latest_snapshots_for_upcoming()
    games: dict[int, Game] = {}
    books_by_game: dict[int, list[Sportsbook]] = defaultdict(list)
    for s in snaps:
        games[s.game_id] = s.game
        if s.sportsbook not in books_by_game[s.game_id]:
            books_by_game[s.game_id].append(s.sportsbook)
    return sorted(games.values(), key=lambda g: g.commence_time), books_by_game


def _selection_label(bet: TrackedBet) -> str:
    """Render a human-readable selection for a stored bet."""
    game = bet.game
    if bet.bet_type == "parlay":
        return f"Parlay ({len(bet.legs)} legs)"
    if bet.bet_type == "moneyline":
        team = game.home_team if bet.selection == "home" else game.away_team
        return f"{team} ML"
    if bet.bet_type == "spread":
        parts = bet.selection.split("|")
        if len(parts) == 2:
            side, line = parts
            team = game.home_team if side == "home" else game.away_team
            try:
                ln = float(line)
                sign = "+" if ln >= 0 else ""
                return f"{team} {sign}{ln}"
            except ValueError:
                return f"{team} {line}"
    if bet.bet_type == "total":
        parts = bet.selection.split("|")
        if len(parts) == 2:
            side, line = parts
            return f"{side.capitalize()} {line}"
    return bet.selection


def _leg_label(leg: ParlayLeg) -> str:
    parts = leg.selection.split("|")
    if not parts:
        return leg.selection
    bet_type = parts[0]
    game = leg.game
    if bet_type == "moneyline" and len(parts) == 2:
        team = game.home_team if parts[1] == "home" else game.away_team
        return f"{team} ML"
    if bet_type == "spread" and len(parts) == 3:
        team = game.home_team if parts[1] == "home" else game.away_team
        try:
            ln = float(parts[2]); sign = "+" if ln >= 0 else ""
            return f"{team} {sign}{ln}"
        except ValueError:
            return f"{team} {parts[2]}"
    if bet_type == "total" and len(parts) == 3:
        return f"{parts[1].capitalize()} {parts[2]}"
    return leg.selection


# ---------- My Bets dashboard ----------


@bets_bp.route("/")
@login_required
def index():
    bets = db.session.execute(
        select(TrackedBet)
        .where(TrackedBet.user_id == current_user.id)
        .order_by(TrackedBet.placed_at.desc())
        .options(
            selectinload(TrackedBet.legs).selectinload(ParlayLeg.game),
        )
    ).scalars().all()

    # Decorate with display labels + game refs.
    rows = []
    for b in bets:
        rows.append({
            "bet": b,
            "label": _selection_label(b),
            "leg_labels": [_leg_label(l) for l in b.legs],
            "pnl": (float(b.payout) - float(b.stake)) if b.payout is not None else None,
        })

    # Summary metrics
    total_bets = len(bets)
    total_staked = sum(float(b.stake) for b in bets)
    total_payout = sum(float(b.payout) for b in bets if b.payout is not None)
    net_pnl = total_payout - sum(float(b.stake) for b in bets if b.status != "pending")
    settled = [b for b in bets if b.status in ("won", "lost", "push")]
    decisive = [b for b in settled if b.status in ("won", "lost")]
    win_rate = (sum(1 for b in decisive if b.status == "won") / len(decisive)) if decisive else None
    roi = (net_pnl / sum(float(b.stake) for b in settled) * 100) if settled else None

    return render_template(
        "bets/index.html",
        rows=rows,
        total_bets=total_bets,
        total_staked=total_staked,
        total_payout=total_payout,
        net_pnl=net_pnl,
        win_rate=win_rate,
        roi=roi,
    )


@bets_bp.route("/analytics.json")
@login_required
def analytics_json():
    """Chart data: cumulative P&L, win rate by sport, win rate by bet type, ROI by book."""
    bets = db.session.execute(
        select(TrackedBet)
        .where(TrackedBet.user_id == current_user.id, TrackedBet.status != "pending")
        .order_by(TrackedBet.settled_at.asc().nulls_last())
        .options(selectinload(TrackedBet.legs))
    ).scalars().all()

    # Cumulative P&L
    cumulative = []
    running = 0.0
    for b in bets:
        if b.payout is None or b.settled_at is None:
            continue
        running += float(b.payout) - float(b.stake)
        cumulative.append({"t": b.settled_at.isoformat(), "v": round(running, 2)})

    # Win rate by sport (single-game bets only, so parlays counted under "Parlay")
    sport_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"won": 0, "lost": 0})
    for b in bets:
        if b.status == "push":
            continue
        if b.bet_type == "parlay":
            key = "Parlay"
        else:
            key = b.game.sport.display_name if b.game else "Other"
        sport_stats[key][b.status] = sport_stats[key].get(b.status, 0) + 1
    win_rate_by_sport = [
        {"label": k, "rate": v["won"] / (v["won"] + v["lost"])}
        for k, v in sport_stats.items() if (v["won"] + v["lost"]) > 0
    ]

    # Win rate by bet type
    type_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"won": 0, "lost": 0})
    for b in bets:
        if b.status == "push":
            continue
        type_stats[b.bet_type][b.status] += 1
    win_rate_by_type = [
        {"label": k, "rate": v["won"] / (v["won"] + v["lost"])}
        for k, v in type_stats.items() if (v["won"] + v["lost"]) > 0
    ]

    # ROI by sportsbook
    book_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"stake": 0.0, "payout": 0.0})
    books_by_id = {b.id: b for b in db.session.execute(select(Sportsbook)).scalars()}
    for b in bets:
        if b.payout is None:
            continue
        book_name = books_by_id[b.sportsbook_id].display_name if b.sportsbook_id in books_by_id else "Unknown"
        book_stats[book_name]["stake"] += float(b.stake)
        book_stats[book_name]["payout"] += float(b.payout)
    roi_by_book = [
        {"label": k, "roi": (v["payout"] - v["stake"]) / v["stake"] * 100}
        for k, v in book_stats.items() if v["stake"] > 0
    ]

    return jsonify({
        "cumulative_pnl": cumulative,
        "win_rate_by_sport": win_rate_by_sport,
        "win_rate_by_type": win_rate_by_type,
        "roi_by_book": roi_by_book,
    })


# ---------- Create a single bet ----------


@bets_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        try:
            game_id = int(request.form["game_id"])
            sportsbook_id = int(request.form["sportsbook_id"])
            bet_type = request.form["bet_type"]
            side = request.form["side"]
            odds = _parse_decimal(request.form.get("odds"), "odds")
            stake = _parse_decimal(request.form.get("stake"), "stake")
            line_raw = request.form.get("line", "").strip()

            if bet_type not in ALLOWED_BET_TYPES:
                raise ValueError("invalid bet_type")
            if side not in ALLOWED_SIDES[bet_type]:
                raise ValueError("invalid side")
            if stake <= 0:
                raise ValueError("stake must be positive")
            # Validate odds via conversion (raises on bad input).
            american_to_decimal(float(odds))

            if bet_type == "moneyline":
                selection = side
            else:
                if not line_raw:
                    raise ValueError("line is required for spread/total bets")
                line_val = float(line_raw)
                selection = f"{side}|{line_val}"

            game = db.session.get(Game, game_id)
            book = db.session.get(Sportsbook, sportsbook_id)
            if game is None or book is None:
                raise ValueError("unknown game or sportsbook")

            bet = TrackedBet(
                user_id=current_user.id,
                game_id=game_id,
                sportsbook_id=sportsbook_id,
                bet_type=bet_type,
                selection=selection,
                odds_at_bet=odds,
                stake=stake,
            )
            db.session.add(bet)
            db.session.commit()
            flash("Bet logged.", "info")
            return redirect(url_for("bets.index"))
        except (ValueError, KeyError) as e:
            flash(f"Could not log bet: {e}", "error")

    games, books_by_game = _upcoming_games_with_books()
    # Prefill from query params (used by "Log bet" links on Live Odds).
    prefill = {
        "game_id": request.args.get("game_id", ""),
        "sportsbook_id": request.args.get("sportsbook_id", ""),
        "bet_type": request.args.get("bet_type", "moneyline"),
        "side": request.args.get("side", "home"),
        "odds": request.args.get("odds", ""),
        "line": request.args.get("line", ""),
    }
    return render_template(
        "bets/new.html",
        games=games,
        books_by_game={k: [{"id": b.id, "name": b.display_name} for b in v] for k, v in books_by_game.items()},
        prefill=prefill,
    )


# ---------- Create a parlay ----------


@bets_bp.route("/new-parlay", methods=["GET", "POST"])
@login_required
def new_parlay():
    if request.method == "POST":
        try:
            sportsbook_id = int(request.form["sportsbook_id"])
            stake = _parse_decimal(request.form.get("stake"), "stake")
            if stake <= 0:
                raise ValueError("stake must be positive")

            legs_data: list[dict] = []
            # Form sends leg_count and leg_0_*, leg_1_*, ...
            leg_count = int(request.form.get("leg_count", "0"))
            if not 2 <= leg_count <= 10:
                raise ValueError("parlay must have 2-10 legs")
            for i in range(leg_count):
                game_id = int(request.form[f"leg_{i}_game_id"])
                bet_type = request.form[f"leg_{i}_bet_type"]
                side = request.form[f"leg_{i}_side"]
                odds = _parse_decimal(request.form.get(f"leg_{i}_odds"), f"leg_{i}_odds")
                line_raw = request.form.get(f"leg_{i}_line", "").strip()
                if bet_type not in ALLOWED_BET_TYPES:
                    raise ValueError(f"invalid bet_type on leg {i + 1}")
                if side not in ALLOWED_SIDES[bet_type]:
                    raise ValueError(f"invalid side on leg {i + 1}")
                american_to_decimal(float(odds))
                if bet_type == "moneyline":
                    selection = f"moneyline|{side}"
                else:
                    if not line_raw:
                        raise ValueError(f"line required on leg {i + 1}")
                    selection = f"{bet_type}|{side}|{float(line_raw)}"
                legs_data.append({
                    "game_id": game_id, "selection": selection, "odds": odds,
                })

            # Combined decimal odds for display label.
            combined = 1.0
            for l in legs_data:
                combined *= american_to_decimal(float(l["odds"]))

            bet = TrackedBet(
                user_id=current_user.id,
                game_id=None,
                sportsbook_id=sportsbook_id,
                bet_type="parlay",
                selection=f"{leg_count}-leg parlay",
                odds_at_bet=Decimal(f"{combined:.4f}"),  # store combined decimal
                stake=stake,
            )
            db.session.add(bet)
            db.session.flush()
            for l in legs_data:
                db.session.add(ParlayLeg(
                    parlay_bet_id=bet.id,
                    game_id=l["game_id"],
                    selection=l["selection"],
                    odds=l["odds"],
                ))
            db.session.commit()
            flash("Parlay logged.", "info")
            return redirect(url_for("bets.index"))
        except (ValueError, KeyError) as e:
            flash(f"Could not log parlay: {e}", "error")

    games, books_by_game = _upcoming_games_with_books()
    books = db.session.execute(select(Sportsbook).order_by(Sportsbook.display_name)).scalars().all()
    return render_template("bets/new_parlay.html", games=games, sportsbooks=books)
