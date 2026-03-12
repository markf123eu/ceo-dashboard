import os, base64, json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

GMAIL_FROM            = os.getenv("GMAIL_FROM")
FACEBOOK_AGENCY_EMAIL = os.getenv("FACEBOOK_AGENCY_EMAIL")
GOOGLE_AGENCY_EMAIL   = os.getenv("GOOGLE_AGENCY_EMAIL")
CLIENT_ID             = os.getenv("GOOGLE_ADS_CLIENT_ID")
CLIENT_SECRET         = os.getenv("GOOGLE_ADS_CLIENT_SECRET")
REFRESH_TOKEN         = os.getenv("GOOGLE_ADS_REFRESH_TOKEN")

def _get_gmail_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return build("gmail", "v1", credentials=creds)

def _send_email(to, subject, body):
    service = _get_gmail_service()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_FROM
    msg["To"]      = to
    msg.attach(MIMEText(body, "plain"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"  ✅ Email sent to {to}")

def _eur(value):
    return f"€{value:,.2f}" if value is not None else "N/A"

def _wow(curr, prev, unit=""):
    if prev is None or curr is None: return ""
    diff = curr - prev
    if diff > 0: return f"▲ +{diff}{unit} vs last week"
    if diff < 0: return f"▼ {diff}{unit} vs last week"
    return "→ Same as last week"

def _wow_eur(curr, prev):
    if prev is None or curr is None: return ""
    diff = round(curr - prev, 2)
    if diff > 0: return f"▲ CPL up +€{diff} vs last week"
    if diff < 0: return f"▼ CPL down €{abs(diff)} vs last week"
    return "→ Same as last week"

def send_facebook_email(data, prev_data=None):
    t      = data["totals"]
    g      = data["geography"]
    cpl    = data["cpl"]
    tl     = data["timelines"]
    hiring = data.get("hiring", {})
    total  = t["unique"]
    asap   = tl.get("asap", 0)
    within_1m = tl.get("within_1_month", 0)

    prev_total = prev_data["totals"]["unique"]       if prev_data else None
    prev_cpl   = prev_data["cpl"]["overall"]         if prev_data else None
    prev_asap  = prev_data["timelines"].get("asap",0) if prev_data else None

    dublin_total  = g["within_10km"] + g["band_10_20km"]
    outside_total = g["outside_20km"]

    # Campaign table
    camp_lines = []
    for camp, info in sorted(cpl["by_campaign"].items(), key=lambda x: x[1]["spend"], reverse=True)[:5]:
        short = camp.replace("_Dublin_ACB","").replace("_Dublin","")[:40]
        camp_lines.append(f"  {short}\n    Leads: {info['leads']} | Spend: {_eur(info['spend'])} | CPL: {_eur(info['cpl'])}")
    camp_text = "\n".join(camp_lines)

    period_label = f"{data['period']['from']} to {data['period']['to']}"

    body = f"""Hi,

Please find below this week's Facebook Ads performance report for Energy Upgrade.

WEEKLY FACEBOOK REPORT — {period_label}
{'='*55}

OVERVIEW
--------
Total Leads:     {total} unique  ({t['duplicates']} duplicates removed)
                 {_wow(total, prev_total)}
Total Spend:     {_eur(cpl['total_spend'])}
CPL:             {_eur(cpl['overall'])}
                 {_wow_eur(cpl['overall'], prev_cpl)}
Hot Leads:       {asap + within_1m} (ASAP or within 1 month)
                 {_wow(asap, prev_asap, ' ASAP leads')}

GEOGRAPHIC BREAKDOWN
--------------------
Total Dublin (within 20km):  {dublin_total} leads  ({round(dublin_total/total*100) if total else 0}%)
  - Core Dublin (within 10km): {g['within_10km']} leads
  - Greater Dublin (10-20km):  {g['band_10_20km']} leads
Outside Dublin:              {outside_total} leads  ({round(outside_total/total*100) if total else 0}%)
Unknown eircode:             {g['unknown']} leads

NOTE: We are seeing {round(outside_total/total*100) if total else 0}% of leads coming from outside our service area. 
Please ensure location targeting is set to 'People who live in this location' 
and that 'Reach more people likely to respond' is disabled. 
Our target is 85%+ of leads from Dublin.

CAMPAIGN PERFORMANCE
--------------------
{camp_text}

PURCHASE INTENT
---------------
""" + "\n".join(f"  {k.replace('_',' ').title()}: {v} leads" for k,v in list(tl.items())[:5]) + f"""

HIRING CAMPAIGN (separate — not included above)
------------------------------------------------
Leads: {hiring.get('leads', 0)} | Spend: {_eur(hiring.get('spend', 0))}

TARGETS & ACTIONS REQUIRED
---------------------------
1. Target: 100+ Facebook leads per week (currently {total})
2. Fix geo-targeting — reduce outside Dublin leads below 15%
3. Scale budget no more than 20% per week
4. Maintain CPL below €25 — flag immediately if any campaign exceeds €30
5. Pause underperforming campaigns and reallocate to top 2-3 performers

Please come back to us with your plan for the week ahead.



Thanks,
Energy Upgrade
"""

    subject = f"Weekly Facebook Ads Report — {period_label}"
    _send_email(FACEBOOK_AGENCY_EMAIL, subject, body)


def send_google_email(ga_data, ga_prev=None):
    if not ga_data:
        print("  ⚠️  No Google Ads data — skipping email")
        return

    t     = ga_data["totals"]
    camps = ga_data["campaigns"]

    prev_leads = ga_prev["totals"]["leads"] if ga_prev else None
    prev_cpl   = ga_prev["totals"]["cpl"]   if ga_prev else None

    camp_lines = []
    for camp, info in list(camps.items())[:5]:
        camp_lines.append(f"  {camp[:45]}\n    Leads: {info['leads']} | Spend: {_eur(info['spend'])} | CPL: {_eur(info['cpl'])} | CTR: {info['ctr']}%")
    camp_text = "\n".join(camp_lines)

    period_label = f"Last 7 days to {datetime.utcnow().strftime('%d %b %Y')}"

    body = f"""Hi,

Please find below this week's Google Ads performance report for Energy Upgrade.

WEEKLY GOOGLE ADS REPORT — {period_label}
{'='*55}

OVERVIEW
--------
Total Leads:     {t['leads']}
                 {_wow(t['leads'], prev_leads)}
Total Spend:     {_eur(t['spend'])}
CPL:             {_eur(t['cpl'])}
                 {_wow_eur(t['cpl'], prev_cpl)}
CTR:             {t['ctr']}%
Clicks:          {t['clicks']}
Impressions:     {t['impressions']}

CAMPAIGN PERFORMANCE
--------------------
{camp_text}

TARGETS & ACTIONS REQUIRED
---------------------------
1. Target: 50+ Google leads per week (currently {t['leads']})
2. Scale GB_Gas Boiler — our strongest performer, increase budget max 20% per week
3. Maintain CPL below €40 — flag immediately if exceeding
4. Review keyword targeting for high-intent Dublin boiler replacement searches
5. Explore Oil Boiler replacement campaign on Google

Please come back to us with your plan for the week ahead.



Thanks,
Energy Upgrade
"""

    subject = f"Weekly Google Ads Report — {period_label}"
    _send_email(GOOGLE_AGENCY_EMAIL, subject, body)


def send_all(data, prev_data=None, ga_data=None, ga_prev=None):
    print("\nSending agency emails...")
    send_facebook_email(data, prev_data)
    send_google_email(ga_data, ga_prev)
    print("✅ All agency emails sent")


if __name__ == "__main__":
    print("Email reporter ready")
