import os, json, requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "config/.env"))

app = Flask(__name__)

SLACK_BOT_TOKEN  = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
HUBSPOT_TOKEN    = os.getenv("HUBSPOT_TOKEN")
JOBBER_ACCESS_TOKEN  = os.getenv("JOBBER_ACCESS_TOKEN")
JOBBER_REFRESH_TOKEN = os.getenv("JOBBER_REFRESH_TOKEN")
JOBBER_CLIENT_ID     = os.getenv("JOBBER_CLIENT_ID")
JOBBER_CLIENT_SECRET = os.getenv("JOBBER_CLIENT_SECRET")

# HubSpot Sales Pipeline stage IDs
HUBSPOT_PIPELINE_ID = "default"
STAGE_MAP = {
    "REQUEST_UPDATE":  "qualifiedtobuy",
    "QUOTE_SENT":      "presentationscheduled",
    "QUOTE_UPDATE":    "1446705391",
    "JOB_UPDATE":      "contractsent",
    "VISIT_COMPLETE":  "closedwon",
    "PAYMENT_CREATE":  "closedwon",
}

SLACK_MESSAGES = {
    "CLIENT_CREATE":   ("👤 New Client", "A new client has been added in Jobber"),
    "REQUEST_UPDATE":  ("📋 New Request", "A new request has been created in Jobber"),
    "QUOTE_SENT":      ("📝 Quote Sent", "A quote has been sent to a client"),
    "QUOTE_UPDATE":    ("✅ Quote Approved", "A quote has been approved"),
    "JOB_UPDATE":      ("🔧 Job Scheduled", "A job has been scheduled"),
    "VISIT_COMPLETE":  ("🎉 Job Completed", "A job has been completed"),
    "PAYMENT_CREATE":  ("💰 Payment Received", "A payment has been received"),
    "EXPENSE_CREATE":  ("🧾 Expense Added", "A new expense has been recorded"),
    "TIMESHEET_CREATE":("⏱️ Timesheet Entry", "A new timesheet entry has been added"),
}

def post_to_slack(title, message, details=None, color="#36a64f"):
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{message}"}},
    ]
    if details:
        fields = [{"type": "mrkdwn", "text": f"*{k}*\n{v}"} for k, v in details.items()]
        blocks.append({"type": "section", "fields": fields[:10]})

    resp = requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json={"channel": SLACK_CHANNEL_ID, "text": title, "blocks": blocks})
    return resp.json()

def get_hubspot_contact(email):
    if not email: return None
    resp = requests.get(f"https://api.hubapi.com/crm/v3/objects/contacts/search",
        headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
        json={"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
              "properties": ["firstname", "lastname", "email", "hs_lead_source"]})
    results = resp.json().get("results", [])
    return results[0] if results else None

def create_or_update_hubspot_deal(contact_id, deal_name, stage_id, amount=None, jobber_id=None):
    props = {
        "dealname": deal_name,
        "pipeline": HUBSPOT_PIPELINE_ID,
        "dealstage": stage_id,
    }
    if amount: props["amount"] = amount
    if jobber_id: props["description"] = f"Jobber ID: {jobber_id}"

    # Search for existing deal
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

def fetch_jobber_client(client_id):
    resp = requests.post("https://api.getjobber.com/api/graphql",
        headers={"Authorization": f"Bearer {JOBBER_ACCESS_TOKEN}", "Content-Type": "application/json"},
        json={"query": f"""
            query {{
                client(id: "{client_id}") {{
                    id name emails {{ address }} phones {{ number }}
                    billingAddress {{ street city postalCode }}
                }}
            }}
        """})
    return resp.json().get("data", {}).get("client")

@app.route("/webhook/jobber", methods=["POST"])
def jobber_webhook():
    try:
        data = request.json
        topic = data.get("topic", "")
        payload = data.get("data", {})

        print(f"Received webhook: {topic}")
        print(json.dumps(data, indent=2))
        
        # Post to Slack immediately regardless of client lookup
        if topic in SLACK_MESSAGES:
            title, msg = SLACK_MESSAGES[topic]
            slack_result = post_to_slack(title, msg, {"Topic": topic})
            print(f"Slack result: {slack_result}")

        # Get client info if available
        client_id = payload.get("clientId") or payload.get("client_id")
        client = fetch_jobber_client(client_id) if client_id else None
        client_name = client.get("name", "Unknown") if client else payload.get("client_name", "Unknown")
        client_email = client.get("emails", [{}])[0].get("address") if client else None

        # Build Slack details
        details = {"👤 Client": client_name}
        if payload.get("jobNumber"): details["📋 Job #"] = str(payload.get("jobNumber"))
        if payload.get("total"): details["💶 Value"] = f"€{payload.get('total')}"
        if payload.get("title"): details["📌 Title"] = payload.get("title")

        # Post to Slack
        if topic in SLACK_MESSAGES:
            title, msg = SLACK_MESSAGES[topic]
            post_to_slack(title, msg, details)

        # Update HubSpot
        if topic in STAGE_MAP and client_email:
            contact = get_hubspot_contact(client_email)
            contact_id = contact["id"] if contact else None
            jobber_id = payload.get("id", "")
            deal_name = f"{client_name} — Boiler Replacement"
            create_or_update_hubspot_deal(contact_id, deal_name, STAGE_MAP[topic], 
                amount=payload.get("total"), jobber_id=jobber_id)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Error: {e}")
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
    result = post_to_slack("🧪 Test", "Webhook server is working!", {"Status": "Connected"})
    return jsonify(result), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

