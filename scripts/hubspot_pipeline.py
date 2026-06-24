import os, requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}

def get_pipeline_id(pipeline_name):
    """Find a deal pipeline ID by name."""
    resp = requests.get(
        "https://api.hubapi.com/crm/v3/pipelines/deals",
        headers=HEADERS
    )
    for p in resp.json().get("results", []):
        if pipeline_name.lower() in p["label"].lower():
            return p["id"], p.get("stages", [])
    return None, []

def get_stage_id(stages, stage_name):
    """Find a stage ID by name within a pipeline's stages."""
    for s in stages:
        if stage_name.lower() in s["label"].lower():
            return s["id"]
    return None

def fetch_hp_qualified(since, until):
    """
    Fetch heat pump deals that moved into 'Qualified' stage this week.
    Returns count and list of deals.
    """
    pipeline_id, stages = get_pipeline_id("heatpump")
    if not pipeline_id:
        print("  ⚠️  Could not find Heatpump pipeline in HubSpot")
        return {"count": 0, "deals": [], "pipeline_found": False}

    qualified_stage_id = get_stage_id(stages, "qualified")
    if not qualified_stage_id:
        print("  ⚠️  Could not find Qualified stage in Heatpump pipeline")
        return {"count": 0, "deals": [], "pipeline_found": True, "stage_found": False}

    print(f"  Found pipeline: {pipeline_id}, stage: {qualified_stage_id}")

    # Search for deals in the qualified stage, updated in the date range
    since_ms = int(since.replace(tzinfo=timezone.utc).timestamp() * 1000)
    until_ms = int(until.replace(tzinfo=timezone.utc).timestamp() * 1000)

    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "pipeline", "operator": "EQ", "value": pipeline_id},
                {"propertyName": "dealstage", "operator": "EQ", "value": qualified_stage_id},
                {"propertyName": "hs_lastmodifieddate", "operator": "BETWEEN",
                 "highValue": str(until_ms), "value": str(since_ms)},
            ]
        }],
        "properties": ["dealname", "dealstage", "pipeline", "hs_lastmodifieddate",
                       "amount", "hubspot_owner_id"],
        "limit": 100,
    }

    resp = requests.post(
        "https://api.hubapi.com/crm/v3/objects/deals/search",
        headers=HEADERS,
        json=payload
    )
    data = resp.json()
    deals = data.get("results", [])

    return {
        "count": len(deals),
        "deals": [{"name": d["properties"].get("dealname", "Unknown"),
                   "amount": d["properties"].get("amount"),
                   "modified": d["properties"].get("hs_lastmodifieddate", "")}
                  for d in deals],
        "pipeline_found": True,
        "stage_found": True,
    }

def fetch_new_contacts_by_type(since, until):
    """
    Fetch new HubSpot contacts created in the period,
    split by boiler vs heat pump based on 'first_conversion' field.
    """
    since_ms = int(since.replace(tzinfo=timezone.utc).timestamp() * 1000)
    until_ms = int(until.replace(tzinfo=timezone.utc).timestamp() * 1000)

    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "createdate", "operator": "BETWEEN",
                 "highValue": str(until_ms), "value": str(since_ms)},
            ]
        }],
        "properties": ["firstname", "lastname", "email", "phone",
                       "first_conversion_event_name", "hs_analytics_first_url"],
        "limit": 100,
    }

    resp = requests.post(
        "https://api.hubapi.com/crm/v3/objects/contacts/search",
        headers=HEADERS,
        json=payload
    )

    contacts = resp.json().get("results", [])
    boiler = []
    heatpump = []
    hiring = []
    other = []

    HIRING_KEYWORDS = ["hiring", "recruit", "job", "career", "vacancy", "staff"]

    for c in contacts:
        props = c.get("properties", {})
        source = (props.get("first_conversion_event_name") or "").lower()
        name = f"{props.get('firstname', '')} {props.get('lastname', '')}".strip()
        entry = {
            "name": name,
            "email": props.get("email", ""),
            "phone": props.get("phone", ""),
            "source": props.get("first_conversion_event_name", ""),
        }
        if any(k in source for k in HIRING_KEYWORDS):
            hiring.append(entry)
        elif "hp" in source or "heat pump" in source or "heatpump" in source:
            heatpump.append(entry)
        elif source:
            boiler.append(entry)
        else:
            other.append(entry)

    return {
        "boiler": boiler,
        "heatpump": heatpump,
        "hiring": hiring,
        "other": other,
        "total": len(contacts),
    }

if __name__ == "__main__":
    from datetime import datetime, timedelta
    until = datetime.utcnow()
    since = until - timedelta(days=7)
    print("Fetching HP qualified leads...")
    result = fetch_hp_qualified(since, until)
    print(f"Qualified HP deals: {result['count']}")
    print("Fetching contacts by type...")
    contacts = fetch_new_contacts_by_type(since, until)
    print(f"Boiler: {len(contacts['boiler'])}, HP: {len(contacts['heatpump'])}, Hiring: {len(contacts['hiring'])}")
