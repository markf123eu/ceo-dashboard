# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A marketing/sales reporting system for **Energy Upgrade** (an Irish boiler & heat-pump installer). It pulls lead and ad-spend data from Facebook Lead Ads, Google Ads, HubSpot, and Jobber, then pushes formatted reports to Slack and email. It also runs a live webhook server that syncs Jobber/HubSpot events into Slack notifications and HubSpot deals.

There are two long-running processes plus a set of standalone report scripts:

1. **`scheduler.py`** — runs the weekly + daily report scripts on a cron-like schedule.
2. **`jobber_webhook.py`** — a Flask server handling inbound webhooks and OAuth callbacks.

`start.py` launches both in parallel threads (the production entrypoint on Render).

## Running

```bash
pip install -r requirements.txt

# Both background processes together (production entrypoint)
python3 start.py

# Just the scheduler (runs weekly report immediately on startup, then schedules)
python3 scheduler.py

# Just the Flask webhook server (PORT env var, defaults to 8080)
python3 jobber_webhook.py

# Generate the weekly report manually
python3 scripts/run_report.py            # posts to Slack + emails agencies
python3 scripts/run_report.py --no-email # Slack only
python3 scripts/run_report.py --dry-run  # compute + save data/latest.json, send nothing

# Daily leads report
python3 scripts/daily_report.py
python3 scripts/daily_report.py --dry-run

# Each data-source module is independently runnable for debugging (prints JSON):
python3 scripts/facebook_leads.py
python3 scripts/google_ads.py
python3 scripts/hubspot_pipeline.py
python3 scripts/jobber_surveys.py
python3 scripts/week_utils.py
```

There is no test suite, linter, or build step. The `if __name__ == "__main__"` block in each module *is* the smoke test — run the module directly to exercise its fetch against the live API.

## Configuration

All secrets load from `config/.env` (gitignored) via `python-dotenv`. Every script calls `load_dotenv(".../config/.env")` relative to its own location. Key env vars by integration:

- **Slack**: `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID` (weekly), `SLACK_DAILY_CHANNEL_ID` (daily), `SLACK_BOILER_LEADS_CHANNEL`, `SLACK_HP_LEADS_CHANNEL` (live lead alerts)
- **Facebook**: `FB_PAGE_TOKEN`, `FB_PAGE_ID` (ad account ID `FB_AD_ACCOUNT_ID` is hardcoded in `facebook_leads.py`)
- **Google Ads / Gmail**: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_CUSTOMER_ID`, `GOOGLE_ADS_MANAGER_CUSTOMER_ID`. **The same Google OAuth client/refresh token is reused for Gmail sending** in `email_reporter.py`.
- **HubSpot**: `HUBSPOT_TOKEN`
- **Jobber**: `JOBBER_CLIENT_ID`, `JOBBER_CLIENT_SECRET`, `JOBBER_ACCESS_TOKEN`, `JOBBER_REFRESH_TOKEN`
- **Render** (token persistence): `RENDER_API_KEY`
- `COMPANY_NAME`, `GMAIL_FROM`, `FACEBOOK_AGENCY_EMAIL`, `GOOGLE_AGENCY_EMAIL`

## Architecture & cross-cutting concepts

### Report pipeline (`scripts/run_report.py` is the orchestrator)
`run_report.py` is the hub: it imports every data-source module, fetches the current week and the prior week (for week-over-week deltas), splits everything into **boiler vs heat-pump (HP)** streams, computes combined totals, writes `data/latest.json`, then hands the assembled `data` dict to `slack_reporter.build_report()` and `email_reporter.send_all()`. The flow is:

```
week_utils → date ranges
facebook_leads.fetch_and_analyse → leads, CPL, geography, dedup
google_ads.fetch_and_analyse     → spend/leads per campaign
jobber_surveys.fetch_site_surveys → survey count (proxy = Jobber requests)
hubspot_pipeline.fetch_hp_*       → HP pipeline stage counts + weekly qualified
        ↓ assembled into one `data` dict
slack_reporter.build_report  → Slack Block Kit blocks → post_to_slack
email_reporter.send_all      → plaintext emails to the FB & Google agencies
```

Every external fetch in `run_report.py` is wrapped in try/except so one failing API doesn't kill the whole report — failures degrade to `None`/zero and the report still posts.

### Boiler vs Heat-Pump classification (pervasive)
The whole system bifurcates leads/spend/campaigns into **boiler** and **HP**. Classification is by string matching on campaign/source names, duplicated across modules (each defines its own `is_hp_campaign`/`is_hp_lead` and `HIRING_KEYWORDS`):
- HP = `"hp"` (or "heat pump"/"heatpump") appears in the name.
- **Hiring campaigns** (keywords: hiring, recruit, job, career, vacancy, staff) are recruitment ads and are **always excluded** from lead/spend metrics.
If you change classification logic, update it in `facebook_leads.py`, `google_ads.py`, `slack_reporter.py`, `run_report.py`, and `jobber_webhook.py` — they don't share a helper.

### Geography / eircode scoring (`facebook_leads.py`)
Leads are scored by distance from Dublin city centre using a hardcoded `EIRCODE_COORDS` lookup + haversine. Zones: `within_10km`, `10_20km`, `outside_20km`, `unknown`. "Priority"/"hot" leads = `timeline ∈ {asap, within_1_month}` AND `within_10km`. Outside-Dublin leads are flagged to the agency as a targeting problem (target is 85%+ Dublin).

### Jobber OAuth token refresh + persistence
Jobber access tokens are short-lived. `jobber_graphql()` (defined separately in both `jobber_webhook.py` and `jobber_surveys.py`) retries once on a 401/"expired" by calling `refresh_jobber_token()`. **Critical detail:** because the app runs on Render where the filesystem is ephemeral, refreshed tokens are written back to the Render service environment via `token_manager.persist_jobber_tokens()` — it PUTs the new `JOBBER_ACCESS_TOKEN`/`JOBBER_REFRESH_TOKEN` to both the web and worker services (`RENDER_WEB_SERVICE`/`RENDER_WORKER_SERVICE` IDs hardcoded in `token_manager.py`). Without this, a token refresh would be lost on restart.

### Webhook server (`jobber_webhook.py`)
Flask app with routes:
- `POST /webhook/jobber` — on Jobber events (request/quote/job updates), looks up the record via GraphQL, finds/creates a matching HubSpot deal, and advances it to the mapped pipeline stage (`STAGE_MAP`). Deals are de-duplicated by storing `Jobber ID: <id>` in the deal description.
- `POST /webhook/hubspot` — on `contact.creation`, formats a rich Slack lead alert and routes it to the HP or boiler leads channel (hiring leads skipped).
- `GET /callback` — OAuth authorization-code display (used during Jobber/Google OAuth setup).
- `GET /` health check, `GET /test-slack` connectivity test.

### Slack output
Reports are Slack **Block Kit** JSON (not Markdown). `slack_reporter.py` is mostly presentation: ASCII progress bars (`_bar`/`_goal_bar`), status emojis (`_goal_status`, `_spend_status`, `_capacity_status`), and €/WoW formatting helpers. Business **goals, budgets, and the capacity-scaling model are hardcoded constants at the top of `slack_reporter.py`** (e.g. `BOILER_WEEKLY_LEAD_GOAL`, monthly budgets, `SCALING_MODEL`) — tune targets there.

### Reporting window
`week_utils.get_last_week()` returns the most recent **complete** Monday–Sunday (in UTC); `get_week_before()` is the week prior, used for all WoW comparisons. The daily report instead uses "today so far" (midnight→now UTC).

## Conventions
- All times/dates are **UTC**; currency is **EUR**.
- Modules add their own dir to `sys.path` then import siblings by bare name (`from week_utils import ...`) — they're designed to be run as scripts, not imported as a package.
- HubSpot stage IDs are environment-specific magic strings (`STAGE_MAP` in `jobber_webhook.py`, `HP_PIPELINE_STAGES` in `hubspot_pipeline.py`) — these map to *this* HubSpot account's pipelines and aren't portable.
