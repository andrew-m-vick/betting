# Sports Betting Analytics Platform

A Flask application that ingests live betting odds from The Odds API across seven US sports, provides quantitative tools (EV, Kelly, Monte Carlo parlay sim, arbitrage finder), tracks line movement over time, and lets authenticated users log and analyze their bets.

Built as a portfolio project to demonstrate backend design, quantitative reasoning, API budget management, and full-stack Flask development.

## Live demo

**→ [web-production-daac0.up.railway.app](https://web-production-daac0.up.railway.app/)**

Deployed on Railway; odds refreshed daily from a separate Railway cron service. Add it to your iPhone home screen (Share → Add to Home Screen) for the installable app icon.

## Architecture

```
┌──────────────────┐       ┌────────────────────┐       ┌───────────────────┐
│ The Odds API     │──────▶│  Railway cron      │──────▶│  Neon Postgres    │
│ (free tier, 500  │       │  daily @ 6 AM CT   │       │  (scales to zero) │
│  credits/month)  │       │  refresh_odds.py   │       │                   │
└──────────────────┘       │  ├─ fetch odds     │       │  users            │
                           │  ├─ fetch scores   │       │  sports           │
                           │  │   (in-season)   │       │  sportsbooks      │
                           │  └─ settle bets    │       │  games            │
                           └────────────────────┘       │  odds_snapshots   │
                                    ▲                   │  tracked_bets     │
                                    │                   │  parlay_legs      │
                                    │                   └─────────┬─────────┘
                                    │                             │
                                    │                             ▼
                                    │                   ┌─────────────────────┐
                                    └───────────────────│  Flask app          │
                                                        │  (Railway web)      │
                                                        │                     │
                                                        │  app factory +      │
                                                        │  blueprints:        │
                                                        │    auth, odds,      │
                                                        │    tools, bets,     │
                                                        │    main             │
                                                        │                     │
                                                        │  gunicorn           │
                                                        └─────────────────────┘
```

Key decisions:
- **Append-only odds_snapshots.** The cron writes new rows; "current odds" is defined by a `max(captured_at)` query, never by UPDATE-in-place. This lets the Line Movement page exist with zero extra storage cost.
- **Pure SSR + small JSON endpoints.** Data-heavy pages (Live Odds, Arbitrage, My Bets) are server-rendered. Interactive math (EV Calculator, Parlay Simulator Monte Carlo) is done in the browser — no server round-trip for 10,000-trial simulations.
- **Cron owns all writes from external systems.** The web tier does not fetch from The Odds API. Keeps quota consumption predictable and the web tier latency bounded.

## Tech Stack

- **Backend:** Python 3.11, Flask (app factory + blueprints), SQLAlchemy 2.x, Flask-Migrate (Alembic), Flask-Login, Flask-Bcrypt
- **Database:** PostgreSQL on Neon (serverless)
- **External API:** [The Odds API](https://the-odds-api.com/) (free tier)
- **Frontend:** Server-rendered Jinja templates, Chart.js, KaTeX for math, installable PWA (manifest + service worker)
- **Testing:** pytest (39 tests, SQLite in-memory, zero external API calls)
- **Deployment:** Railway (web + cron), gunicorn

## Features

| Route | Description | Auth |
|---|---|---|
| `/odds/` | Live Odds across 7 sports, sport pill filter, best-odds highlighting in gold | public |
| `/odds/?q=<term>` | Search-results mode with dedicated banner, filters games by team/sport | public |
| `/odds/line-movement` | Time-series chart of how odds moved across books | public |
| `/odds/arbitrage` | Cross-book arb scanner with optimal stake split | public |
| `/ev-calculator` | Expected value + Kelly sizing, live-game odds dropdown | public |
| `/parlay-simulator` | 2–10 leg parlay with 10k-trial Monte Carlo visualization | public |
| `/methodology` | Long-form math explainers with KaTeX (EV, Kelly, arb, CLV, Monte Carlo) | public |
| `/my-bets/` | User bet log, auto-settlement, P&L dashboard with 4 charts | login required |
| `/auth/signup`, `/auth/login`, `/auth/logout` | Email + bcrypt password auth | — |

**Header search** is available on every page: debounced autocomplete against `/odds/search.json`, with keyboard navigation (↑ ↓ Enter Esc). Matches on team names, sport display names, and sport keys using multi-token AND.

**Design system**: stadium-navy base with field-green primary actions and gold "best odds" markers (separated from P&L green to avoid ambiguity). Per-sport accent colors (NFL green, NBA orange, MLB blue, NHL cyan, NCAAF yellow, NCAAB purple, MLS emerald) appear as the left border on each game card and as the dot on each pill.

**Progressive Web App (PWA)**: installable on iOS, Android, and desktop. Ships with:
- A web app manifest at `/manifest.json` declaring `display: standalone`, start URL, theme color, and four **app shortcuts** (Live Odds, EV, Parlay, My Bets) that appear in iOS/Android long-press menus.
- A service worker served from `/service-worker.js` (root-scoped via a Flask route so it controls the whole origin, not just `/static/`). Strategy: precache the app shell on install, then network-first with cache fallback for everything else so the site stays fresh online but opens offline from cache.
- An offline fallback page at `/offline`.
- Dedicated 180×180 `apple-touch-icon.svg` with bolder strokes that survive iOS's rasterization at home-screen sizes, plus maskable-safe content for Android launchers.

To install: desktop Chrome/Edge shows an install icon in the address bar; iOS Safari → Share → Add to Home Screen.

## Sports & books covered

**Sports** (The Odds API keys):
NFL (`americanfootball_nfl`), NBA (`basketball_nba`), MLB (`baseball_mlb`), NHL (`icehockey_nhl`), NCAAF (`americanfootball_ncaaf`), NCAAB (`basketball_ncaab`), MLS (`soccer_usa_mls`).

**Sportsbooks**: DraftKings, FanDuel, BetMGM, Caesars, BetRivers, PointsBet.

## Local setup

```bash
# Requires Python 3.11+ and a Neon connection string.
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in DATABASE_URL, ODDS_API_KEY, SECRET_KEY.

export FLASK_APP=wsgi.py
flask db upgrade
python scripts/refresh_odds.py --sports=nfl   # pulls real odds (uses ~3 credits)

python wsgi.py  # http://localhost:5000
```

Run the tests:

```bash
pytest
```

## Deployment

See [docs/DEPLOY.md](docs/DEPLOY.md) for step-by-step Railway + Neon setup, including the separate cron service.

## The Odds API quota

Free tier is 500 credits/month. The cron runs three steps:

| Step | Cost model | Typical daily cost |
|---|---|---|
| `/odds` refresh | `sports × regions × markets` | 7 × 1 × 3 = 21 credits |
| `/scores` refresh | `1 per in-season sport` | 2–4 credits (only sports with recent games) |
| Bet settlement | local computation | 0 |

That's roughly 15–25 credits/day → 450–750/month. The `/scores` step skips sports with no games commenced in the last 3 days (see `in_season_sport_keys` in [app/services/scores_ingest.py](app/services/scores_ingest.py)), which typically keeps the platform inside 500/month. If you see quota running low, drop `--markets=h2h,spreads` (14 credits/day).

Every Odds API response logs `x-requests-remaining` so quota is always observable.

## Honest notes & limitations

- **Line movement data accumulates over time.** History starts when ingestion started — the app does not backfill. Games played before the cron's first run have no movement data.
- **Arbitrage requires two funded accounts.** No single sportsbook accepts both sides of the same market on one account — the finder surfaces opportunities that require bets at *different* books. Even then, line movement, per-wager limits, and arb-account flagging make US-sports arb fleeting at best. The more practical real-world equivalent is in-game hedging.
- **Settlement is cron-driven.** Bets on a just-completed game are settled on the next cron run, up to 24 hours later.
- **Parlay simulator assumes independent legs.** Same-game parlays (correlated outcomes) will not be modeled accurately. Legs on opposite sides of the same market always lose in reality and sportsbooks wouldn't accept the ticket anyway — the simulator doesn't currently prevent you from entering them.
- **Not a sportsbook.** The app is a tracking and analysis tool. It does not place bets with any sportsbook, and any bets logged in My Bets are self-reported.

## Roadmap (done)

- **Week 1**: foundation — app factory, models, migrations on Neon, auth, Odds API fetcher for NFL, end-to-end test.
- **Week 2**: ingestion for all 7 sports, Live Odds, EV Calculator, Parlay Simulator, Arbitrage Finder.
- **Week 3** (this commit): Line Movement, My Bets with auto-settlement and analytics dashboard, Methodology page, responsive polish, 404/500 pages, Railway deployment artifacts.

## Repo layout

```
betting/
├── app/
│   ├── __init__.py          # app factory + error handlers
│   ├── extensions.py
│   ├── models.py            # SQLAlchemy models
│   ├── auth/                # signup / login / logout
│   ├── odds/                # Live Odds, Line Movement, Arbitrage, upcoming JSON
│   ├── tools/               # EV Calculator, Parlay Simulator
│   ├── bets/                # My Bets (auth-gated) + analytics JSON
│   ├── main/                # root redirect + Methodology
│   ├── services/
│   │   ├── odds_api.py      # The Odds API HTTP client
│   │   ├── ingest.py        # upsert games + odds snapshots
│   │   ├── scores_ingest.py # update completed games + scores
│   │   ├── settlement.py    # ML/spread/total/parlay settlement with push handling
│   │   ├── queries.py       # canonical "latest snapshot" query
│   │   └── math_utils.py    # odds, EV, Kelly, arb math (mirrored in /static/js)
│   ├── static/
│   │   ├── css/app.css
│   │   ├── js/              # ev.js, parlay.js, line_movement.js, my_bets.js, search.js
│   │   ├── favicon.svg
│   │   ├── apple-touch-icon.svg
│   │   ├── manifest.json    # PWA manifest (served at /manifest.json)
│   │   └── service-worker.js # served at root /service-worker.js
│   └── templates/           # Jinja templates
├── migrations/              # Alembic via Flask-Migrate
├── scripts/
│   └── refresh_odds.py      # Railway cron entrypoint (odds → scores → settle)
├── tests/                   # 39 tests, SQLite in-memory
├── docs/DEPLOY.md
├── config.py
├── wsgi.py
├── Procfile
├── railway.toml
└── requirements.txt
```
