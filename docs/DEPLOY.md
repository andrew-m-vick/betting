# Deployment Guide

This doc walks through deploying the Flask app + cron to Railway and pointing both at Neon Postgres.

## Prerequisites

- Railway account (https://railway.app)
- Neon database already provisioned (`DATABASE_URL` ready)
- The Odds API key (`ODDS_API_KEY`)
- Git repo pushed to GitHub — Railway deploys from Git

## Step 1 — Create the Railway project

1. In the Railway dashboard, **New Project → Deploy from GitHub repo**.
2. Pick this repo. Railway will detect `requirements.txt` and `Procfile` automatically.
3. Nixpacks will provision a Python 3.11 environment.

## Step 2 — Set environment variables (web service)

In the Railway **Variables** tab for the web service, add:

```
DATABASE_URL=<your Neon connection string with ?sslmode=require>
ODDS_API_KEY=<your Odds API key>
SECRET_KEY=<generate fresh with: python3 -c "import secrets; print(secrets.token_hex(32))">
FLASK_ENV=production
FLASK_APP=wsgi.py
```

**Important:** generate a fresh `SECRET_KEY` — never reuse your local one.

## Step 3 — Deploy

Push to `main`. Railway runs:

1. `pip install -r requirements.txt`
2. `flask db upgrade` (predeploy, from `railway.toml`)
3. `gunicorn wsgi:app ...`

Check the **Deployments** tab for logs. The app is live on the generated `*.up.railway.app` URL.

## Step 4 — Smoke test

Visit the deployment:

- `/` → redirects to `/odds/`
- `/auth/signup` → create a test account
- `/ev-calculator`, `/parlay-simulator`, `/methodology` → render without error
- `/my-bets` (after login) → loads (empty state)

## Step 5 — Create the cron service

Railway runs cron via a **separate service** in the same project:

1. In the Railway project, **+ New → Empty Service**.
2. Connect it to the same GitHub repo.
3. In the new service's **Settings → Deploy**:
   - **Start Command**: `python scripts/refresh_odds.py`
   - **Cron Schedule**: `0 11 * * *` (6 AM Central during standard time; adjust for DST)
4. Copy the env vars from the web service (or use Railway's Variable References).
5. Save. Railway will run the script on the schedule; zero compute cost between runs.

## Cron quota math

- Odds refresh: up to 7 sports × 3 markets = 21 credits/day.
- Scores refresh: only for in-season sports (sports with a game in the last 3 days). Typically 2–4 sports = 2–4 credits/day.
- Settlement: free (local computation).

**Total**: ~17–25 credits/day · 30 days = 510–750/month.

The free tier is 500/month. If you see `x-requests-remaining` dipping near zero in cron logs, drop the markets to `h2h,spreads` (2 markets × 7 sports = 14/day) or reduce to one cron run every 2 days.

## Rolling back

Railway keeps previous deployments. Use **Deployments → Redeploy** on a prior version to roll back.

## Neon cold starts

Neon's free tier scales compute to zero after 5 minutes of inactivity. The first request after inactivity can take 2–4s to warm up. The app handles this transparently (`pool_pre_ping=True`), but the first page load may feel sluggish. This is a free-tier tradeoff, not a bug.
