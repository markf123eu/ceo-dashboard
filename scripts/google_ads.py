import os, json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("GOOGLE_ADS_REFRESH_TOKEN")
CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")
MANAGER_ID = os.getenv("GOOGLE_ADS_MANAGER_CUSTOMER_ID", "").replace("-", "")
HIRING_KEYWORDS = ["hiring", "recruit", "job", "career", "vacancy", "staff"]

def is_hiring(name):
    n = (name or "").lower()
    return any(k in n for k in HIRING_KEYWORDS)

def fetch_and_analyse(since=None, until=None, days_back=7):
    if since is None or until is None:
        until = datetime.utcnow()
        since = until - timedelta(days=days_back)

    from google.ads.googleads.client import GoogleAdsClient
    credentials = {
        "developer_token": DEVELOPER_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "login_customer_id": MANAGER_ID,
        "use_proto_plus": True,
    }
    client = GoogleAdsClient.load_from_dict(credentials)
    service = client.get_service("GoogleAdsService")

    query = f"""
        SELECT campaign.id, campaign.name, metrics.cost_micros,
               metrics.conversions, metrics.clicks, metrics.impressions
        FROM campaign
        WHERE segments.date BETWEEN '{since.strftime("%Y-%m-%d")}' AND '{until.strftime("%Y-%m-%d")}'
    """
    response = service.search(customer_id=CUSTOMER_ID, query=query)

    campaigns = {}
    total_spend = 0.0
    total_leads = 0
    total_clicks = 0
    total_impressions = 0

    for row in response:
        name = row.campaign.name
        if is_hiring(name):
            continue
        spend = row.metrics.cost_micros / 1_000_000
        leads = int(row.metrics.conversions)
        clicks = int(row.metrics.clicks)
        impressions = int(row.metrics.impressions)
        if spend == 0 and leads == 0:
            continue
        campaigns[name] = {
            "spend": round(spend, 2),
            "leads": leads,
            "clicks": clicks,
            "impressions": impressions,
            "cpl": round(spend / leads, 2) if leads else None,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
        }
        total_spend += spend
        total_leads += leads
        total_clicks += clicks
        total_impressions += impressions

    return {
        "source": "google_ads",
        "period": {"from": since.date().isoformat(), "to": until.date().isoformat()},
        "totals": {
            "leads": total_leads,
            "spend": round(total_spend, 2),
            "clicks": total_clicks,
            "impressions": total_impressions,
            "cpl": round(total_spend / total_leads, 2) if total_leads else None,
            "ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions else 0,
        },
        "campaigns": dict(sorted(campaigns.items(), key=lambda x: x[1]["spend"], reverse=True)),
        "generated_at": datetime.utcnow().isoformat(),
    }

if __name__ == "__main__":
    result = fetch_and_analyse()
    print(json.dumps(result, indent=2))
