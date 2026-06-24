import os, requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}

# Known stage IDs from Heatpump Pipeline
HP_PIPELINE_STAGES = {
    "checkout_abandoned": "Qualified",
    "checkout_completed": "Consultation Complete",
    "processed":          "BER / HEA",
    "2478982343":         "Quote Sent",
    "shipped":            "Closed Won",
    "cancelled":          "Closed Lost",
}

def get_pipeline_id(pipeline_name):
    resp = requests.get(
        "https://api.hubapi.com/crm/v3/pipelines/deals",
        headers=HEADERS
    )
    for p in resp.json().get("results", []):
        if pipeline_name.lower() in p["label"].lower():
            return p["id"], p.get("stages", [])
    return None, []

def fetch_hp_pipeline_summary():
    """
    Fetch total deal counts at each stage of the Heatpump pipeline.
    Returns a dict of stage_name -> count.
    """
    pipeline_id, _ = get_pipeline_id("heatpump")
    if not pipeline_id:
        print("  ⚠️  Could not find Heatpump pipeline")
        return {}

    summary = {}
    for stage_id, stage_name in HP_PIPELINE_STAGES.items():
        payload = {
            "filterGroups": [{
                "filters": [
                    {"propertyName": "pipeline",   "operator": "EQ", "value": pipeline_id},
                    {"propertyName": "dealstage",  "operator": "EQ", "value": stage_id},
                ]
            }],
            "properties": ["dealname", "dealstage"],
            "limit": 1,
        }
        resp = requests.post(
            "https://api.hubapi.com/crm/v3/objects/deals/search",
            headers=HEADERS,
            json=payload
        )
        data = resp.json()
        total = data.get("total", 0)
        summary[stage_name] = total

    return summary

def fetch_hp_qualified(since, until):
    """
    Fetch deals that entered the Qualified stage (checkout_abandoned)
    in the given date range. This is the primary weekly metric.
    """
    pipeline_id, _ = get_pipeline_id("heatpump")
    if not pipeline_id:
        print("  ⚠️  Could not find Heatpump pipeline")
        return {"count": 0, "deals": [], "pipeline_found": False}

    qualified_stage_id = "checkout_abandoned"

    since_ms = int(since.replace(tzinfo=timezone.utc).timestamp() * 1000)
    until_ms = int(until.replace(tzinfo=timezone.utc).timestamp() * 1000)

    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "pipeline",           "operator": "EQ",      "value": pipeline_id},
                {"propertyName": "dealstage",          "operator": "EQ",      "value": qualified_stage_id},
                {"propertyName": "hs_lastmodifieddate","operator": "BETWEEN",
                 "highValue": str(until_ms), "value": str(since_ms)},
            ]
        }],
        "properties": ["dealname", "dealstage", "hs_lastmodifieddate", "amount"],
        "limit": 100,
    }

    resp = requests.post(
        "https://api.hubapi.com/crm/v3/objects/deals/search",
        headers=HEADERS,
        json=payload
    )
    data = resp.json()
    deals = data.get("results", [])

    print(f"  HP Qualified this week: {len(deals)}")
    return {
        "count": len(deals),
        "deals": [{"name": d["properties"].get("dealname", "Unknown"),
                   "modified": d["properties"].get("hs_lastmodifieddate", "")}
                  for d in deals],
        "pipeline_found": True,
    }

if __name__ == "__main__":
    from datetime import datetime, timedelta
    until = datetime.utcnow()
    since = until - timedelta(days=7)

    print("Fetching HP pipeline summary...")
    summary = fetch_hp_pipeline_summary()
    for stage, count in summary.items():
        print(f"  {stage}: {count}")

    print("\nFetching HP qualified this week...")
    result = fetch_hp_qualified(since, until)
    print(f"  New qualified: {result['count']}")
