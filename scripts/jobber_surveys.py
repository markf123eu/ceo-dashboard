import os, requests, threading
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

JOBBER_ACCESS_TOKEN  = os.getenv("JOBBER_ACCESS_TOKEN")
JOBBER_REFRESH_TOKEN = os.getenv("JOBBER_REFRESH_TOKEN")
JOBBER_CLIENT_ID     = os.getenv("JOBBER_CLIENT_ID")
JOBBER_CLIENT_SECRET = os.getenv("JOBBER_CLIENT_SECRET")

_token_lock = threading.Lock()
jobber_tokens = {
    "access_token": JOBBER_ACCESS_TOKEN,
    "refresh_token": JOBBER_REFRESH_TOKEN,
}

def refresh_jobber_token():
    with _token_lock:
        print("Refreshing Jobber token...", flush=True)
    resp = requests.post("https://api.getjobber.com/api/oauth/token",
        data={
            "client_id": JOBBER_CLIENT_ID,
            "client_secret": JOBBER_CLIENT_SECRET,
            "refresh_token": jobber_tokens["refresh_token"],
            "grant_type": "refresh_token",
        })
    if resp.status_code == 200 and resp.text.strip():
        try:
            data = resp.json()
            jobber_tokens["access_token"] = data["access_token"]
            jobber_tokens["refresh_token"] = data["refresh_token"]
            print("Jobber token refreshed", flush=True)
            return True
        except Exception as e:
            print(f"Token refresh parse error: {e}", flush=True)
    print("Jobber token refresh failed", flush=True)
    return False

def jobber_graphql(query):
    resp = requests.post("https://api.getjobber.com/api/graphql",
        headers={
            "Authorization": f"Bearer {jobber_tokens['access_token']}",
            "Content-Type": "application/json",
            "X-JOBBER-GRAPHQL-VERSION": "2023-11-15"
        },
        json={"query": query})
    data = resp.json()
    if resp.status_code == 401 or data.get("message") == "Access token expired":
        if refresh_jobber_token():
            resp = requests.post("https://api.getjobber.com/api/graphql",
                headers={
                    "Authorization": f"Bearer {jobber_tokens['access_token']}",
                    "Content-Type": "application/json",
                    "X-JOBBER-GRAPHQL-VERSION": "2023-11-15"
                },
                json={"query": query})
            data = resp.json()
    return data

def fetch_site_surveys(since, until):
    """
    Fetch Jobber requests created in the given period.
    These are used as a proxy for boiler site surveys booked.
    """
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_str = until.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = f"""
        query {{
            requests(
                filter: {{
                    createdAt: {{
                        after: "{since_str}"
                        before: "{until_str}"
                    }}
                }}
                first: 100
            ) {{
                totalCount
                nodes {{
                    id
                    title
                    createdAt
                    client {{
                        name
                        emails {{ address }}
                    }}
                }}
            }}
        }}
    """

    result = jobber_graphql(query)
    requests_data = result.get("data", {}).get("requests", {})
    total = requests_data.get("totalCount", 0)
    nodes = requests_data.get("nodes", [])

    surveys = []
    for r in nodes:
        client = r.get("client", {}) or {}
        emails = client.get("emails", [])
        email = emails[0].get("address") if emails else ""
        surveys.append({
            "id": r.get("id"),
            "title": r.get("title", ""),
            "created": r.get("createdAt", "")[:16].replace("T", " "),
            "client_name": client.get("name", "Unknown"),
            "email": email,
        })

    print(f"  Jobber site surveys: {total} total, {len(nodes)} fetched")
    return {
        "count": total,
        "surveys": surveys,
    }

if __name__ == "__main__":
    from datetime import datetime, timedelta
    until = datetime.utcnow()
    since = until - timedelta(days=7)
    print("Fetching site surveys...")
    result = fetch_site_surveys(since, until)
    print(f"Total: {result['count']}")
    for s in result['surveys'][:5]:
        print(f"  {s['created']} — {s['client_name']} — {s['title']}")
