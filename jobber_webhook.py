import os, json, requests, sys
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from token_manager import persist_jobber_tokens

load_dotenv(os.path.join(os.path.dirname(__file__), "config/.env"))

app = Flask(__name__)

SLACK_BOT_TOKEN              = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID             = os.getenv("SLACK_CHANNEL_ID")
SLACK_BOILER_LEADS_CHANNEL   = os.getenv("SLACK_BOILER_LEADS_CHANNEL")
SLACK_HP_LEADS_CHANNEL       = os.getenv("SLACK_HP_LEADS_CHANNEL")
HUBSPOT_TOKEN                = os.getenv("HUBSPOT_TOKEN")
JOBBER_ACCESS_TOKEN          = os.getenv("JOBBER_ACCESS_TOKEN")
JOBBER_REFRESH_TOKEN         = os.getenv("JOBBER_REFRESH_TOKEN")
JOBBER_CLIENT_ID             = os.getenv("JOBBER_CLIENT_ID")
JOBBER_CLIENT_SECRET         = os.getenv("JOBBER_CLIENT_SECRET")

import threading
_token_lock = threading.Lock()

jobber_tokens = {
    "access_token": JOBBER_ACCESS_TOKEN,
    "refresh_token": JOBBER_REFRESH_TOKEN,
}

HIRING_KEYWORDS = ["hiring", "recruit", "job", "career", "vacancy", "staff"]

def is_hp_lead(source):
    s = (source or "").lower()
    return "hp" in s or "heat pump" in s or "heatpump" in s

def is_hiring_lead(source):
    s = (source or "").lower()
    return any(k in s for k in HIRING_KEYWORDS)

def clean_source(source):
    if not source: return "Unknown"
    s = source.replace("Facebook Lead Ads: ", "")
    s = s.replace("Free Boiler Estimate — EnergyUpgrade.ie: #boiler-estimate-form .estimate-form, .hs-form", "Website Form")
    s = s.replace("Get a Heat pump estimate — EnergyUpgrade.ie: #solar-estimate-form .estimate-form, .hs-form", "Website HP Form")
    s = s.replace("Top-Rated Boiler Services in Ireland | EnergyUpgrade.ie: .g-container", "Website")
    return s[:60]

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
    print(f"Refresh response: {resp.status_code} {resp.text}", flush=True)
    if resp.status_code == 200 and resp.text.strip():
        try:
            data = resp.json()
            jobber_tokens["access_token"] = data["access_token"]
            jobber_tokens["refresh_token"] = data["refresh_token"]
            print(f"Token refreshed successfully", flush=True)
            try:
                persist_jobber_tokens(data["access_token"], data["refresh_token"])
            except Exception as te:
                print(f"  ⚠️  Token persist failed: {te}", flush=True)
            return True
        except Exception as e:
            print(f"Token refresh parse error: {e}", flush=True)
    print(f"Token refresh failed", flush=True)
    return False

def jobber_graphql(query):
    resp = requests.post("https://api.getjobber.com/api/graphql",
        headers={"Authorization": f"Bearer {jobber_tokens['access_token']}", "Content-Type": "application/json", "X-JOBBER-GRAPHQL-VERSION": "2023-11-15"},
        json={"query": query})
    if resp.status_code == 401 or resp.json().get("message") == "Access token expired":
        if refresh_jobber_token():
            resp = requests.post("https://api.getjobber.com/api/graphql",
                headers={"Authorization": f"Bearer {jobber_tokens['access_token']}", "Content-Type": "application/json", "X-JOBBER-GRAPHQL-VERSION": "2023-11-15"},
                json={"query": query})
    return resp.json()

def get_hubspot_contact(email):
    if not email: return None
    resp = requests.get("https://api.hubapi.com/crm/v3/objects/contacts/search",
        headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
        json={"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
              "properties": ["firstname", "lastname", "email", "hs_lead_source"]})
    results = resp.json().get("results", [])
    return results[0] if results else None

def create_or_update_hubspot_deal(contact_id, deal_name, stage_id, amount=None, jobber_id=None):
    props = {"dealname": deal_name, "pipeline": "default", "dealstage": stage_id}
    if amount: props["amount"] = amount
    if jobber_id: props["description"] = f"Jobber ID: {jobber_id}"

    search_resp = requests.post("https://api.hubapi.com/crm/v3/objects/deals/search",
        headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
        json={"filterGroups": [{"filters": [{"propertyName": "description", "operator": "CONTAINS_TOKEN", "value": f"Jobber ID: {jobber_id}"}]}]}) if jobber_id else None

    existing = search_resp.json().get("results", []) if search_resp else []
    if existing:
        deal_id = existing[0]["id"]
        requests.patch(f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": props})
        return deal_id
    else:
        resp = requests.post("https://api.hubapi.com/crm/v3/objects/deals",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": props})
        deal_id = resp.json().get("id")
        if deal_id and contact_id:
            requests.put(f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/contacts/{contact_id}/3",
                headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"})
        return deal_id

def fetch_jobber_request(request_id):
    result = jobber_graphql(f"""
        query {{
            request(id: "{request_id}") {{
                id title
                client {{ id name emails {{ address }} phones {{ number }} }}
            }}
        }}
    """)
    return result.get("data", {}).get("request")

def fetch_jobber_job(job_id):
    result = jobber_graphql(f"""
        query {{
            job(id: "{job_id}") {{
                id title jobNumber total
                client {{ id name emails {{ address }} phones {{ number }} }}
            }}
        }}
    """)
    return result.get("data", {}).get("job")

def fetch_jobber_quote(quote_id):
    result = jobber_graphql(f"""
        query {{
            quote(id: "{quote_id}") {{
                id title total
                client {{ id name emails {{ address }} phones {{ number }} }}
            }}
        }}
    """)
    return result.get("data", {}).get("quote")

STAGE_MAP = {
    "REQUEST_UPDATE": "qualifiedtobuy",
    "QUOTE_SENT":     "presentationscheduled",
    "QUOTE_UPDATE":   "1446705391",
    "JOB_UPDATE":     "contractsent",
    "VISIT_COMPLETE": "closedwon",
    "PAYMENT_CREATE": "closedwon",
}

@app.route("/webhook/jobber", methods=["POST"])
def jobber_webhook():
    try:
        data = request.json
        print(f"RAW PAYLOAD: {json.dumps(data)}", flush=True)
        if "webHookEvent" in data.get("data", {}):
            event = data["data"]["webHookEvent"]
            topic = event.get("topic", "")
            item_id = event.get("itemId", "")
            payload = {"id": item_id, "topic": topic}
        else:
            topic = data.get("topic", "")
            payload = data.get("data", {})

        print(f"Received webhook: {topic}", flush=True)

        item_id = payload.get("id", "")
        client_name = "Unknown"
        client_email = None

        if item_id:
            if topic in ("REQUEST_UPDATE",):
                record = fetch_jobber_request(item_id)
            elif topic in ("QUOTE_SENT", "QUOTE_UPDATE"):
                record = fetch_jobber_quote(item_id)
            elif topic in ("JOB_UPDATE", "VISIT_COMPLETE"):
                record = fetch_jobber_job(item_id)
            else:
                record = None

            if record and record.get("client"):
                client = record["client"]
                client_name = client.get("name", "Unknown")
                emails = client.get("emails", [])
                client_email = emails[0].get("address") if emails else None

        if topic in STAGE_MAP and client_email:
            contact = get_hubspot_contact(client_email)
            contact_id = contact["id"] if contact else None
            deal_name = f"{client_name} — Boiler Replacement"
            create_or_update_hubspot_deal(contact_id, deal_name, STAGE_MAP[topic],
                amount=payload.get("total"), jobber_id=payload.get("id", ""))

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/webhook/hubspot", methods=["POST"])
def hubspot_webhook():
    try:
        events = request.json
        if not events:
            return jsonify({"status": "ok"}), 200

        print(f"HubSpot webhook received: {len(events)} events", flush=True)

        for event in events:
            if event.get("subscriptionType") != "contact.creation":
                continue

            contact_id = event.get("objectId")
            if not contact_id:
                continue

            resp = requests.get(
                f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
                headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
                params={"properties": "firstname,lastname,phone,email,first_conversion_event_name,what_is_your_eircode,when_are_you_looking_to_replace_your_boiler,what_is_your_reason_for_wanting_to_replace"}
            )
            contact = resp.json().get("properties", {})

            first_name = contact.get("firstname", "") or ""
            last_name  = contact.get("lastname", "") or ""
            name       = f"{first_name} {last_name}".strip() or "Unknown"
            phone      = contact.get("phone", "") or "No phone"
            email      = contact.get("email", "") or "No email"
            source     = contact.get("first_conversion_event_name", "") or ""
            eircode    = contact.get("what_is_your_eircode", "") or "—"
            timeline   = contact.get("when_are_you_looking_to_replace_your_boiler", "") or "—"
            reason     = contact.get("what_is_your_reason_for_wanting_to_replace", "") or "—"

            TIMELINE_LABELS = {
                "asap":           "🔥 ASAP",
                "within_1_month": "⚡ Within 1 Month",
                "within_3_months":"📅 Within 3 Months",
                "unknown":        "❓ Unknown",
            }
            timeline_display = TIMELINE_LABELS.get(timeline.lower().replace(" ", "_"), timeline)

            if is_hiring_lead(source):
                print(f"  Skipping hiring lead: {name}", flush=True)
                continue

            hp           = is_hp_lead(source)
            channel      = SLACK_HP_LEADS_CHANNEL if hp else SLACK_BOILER_LEADS_CHANNEL
            icon         = "♨️" if hp else "🔥"
            label        = "Heat Pump" if hp else "Boiler"
            source_clean = clean_source(source)

            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"{icon} New {label} Lead"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Name*\n{name}"},
                    {"type": "mrkdwn", "text": f"*Phone*\n{phone}"},
                    {"type": "mrkdwn", "text": f"*Eircode*\n{eircode}"},
                    {"type": "mrkdwn", "text": f"*Timeline*\n{timeline_display}"},
                ]},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Reason*\n{reason}"},
                    {"type": "mrkdwn", "text": f"*Email*\n{email}"},
                    {"type": "mrkdwn", "text": f"*Source*\n{source_clean}"},
                ]},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Via HubSpot • {label} Lead"}]},
            ]

            result = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
                json={"channel": channel, "text": f"New {label} Lead: {name}", "blocks": blocks}
            ).json()

            if result.get("ok"):
                print(f"  ✅ Posted {label} lead {name} to Slack", flush=True)
            else:
                print(f"  ❌ Slack error: {result.get('error')}", flush=True)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"HubSpot webhook error: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/callback", methods=["GET"])
def callback():
    code = request.args.get("code")
    return f"Authorization code: {code}", 200

@app.route("/", methods=["GET"])
def health():
    return "Energy Upgrade Webhook Server running", 200

@app.route("/test-slack", methods=["GET"])
def test_slack():
    result = requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json={"channel": SLACK_CHANNEL_ID, "text": "🧪 Test", "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*🧪 Test*\nWebhook server is working!"}},
            {"type": "section", "fields": [{"type": "mrkdwn", "text": "*Status*\nConnected"}]}
        ]})
    return jsonify(result.json()), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
