import sys, os, json, argparse
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from week_utils import get_last_week, get_week_before, week_label
from facebook_leads import fetch_and_analyse, fetch_forms, fetch_leads, parse_fields, classify
from google_ads import fetch_and_analyse as ga_fetch
from slack_reporter import build_report, post_to_slack
from email_reporter import send_all

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--no-email", action="store_true")
args = parser.parse_args()

print("\n=== CEO Dashboard — Weekly Report ===\n")

# Get fixed Mon-Sun windows
since, until = get_last_week()
since_prev, until_prev = get_week_before()

print(f"Reporting period: {week_label(since, until)}")
print(f"Comparison period: {week_label(since_prev, until_prev)}\n")

# Facebook this week
data = fetch_and_analyse(since=since, until=until)

# Fetch raw leads for hot leads list
forms = fetch_forms()
all_leads = []
for f in forms:
    all_leads.extend(fetch_leads(f["id"], since, until))
parsed_leads = []
for lead in all_leads:
    fields = parse_fields(lead.get("field_data", []))
    eircode = (fields.get("what_is_your_eircode(dublin_only)?") or
               fields.get("eircode") or fields.get("postcode") or "")
    dist, zone = classify(eircode)
    parsed_leads.append({
        "full_name": fields.get("full_name", "Unknown"),
        "phone": fields.get("phone_number", ""),
        "eircode": eircode,
        "timeline": fields.get("when_are_you_looking_to_replace_your_boiler?", "unknown"),
        "zone": zone,
    })
data["_leads"] = parsed_leads

# Facebook last week for comparison
print("Fetching previous week for comparison...")
prev_data = fetch_and_analyse(since=since_prev, until=until_prev)

# Google Ads
print("Fetching Google Ads data...")
try:
    ga_data = ga_fetch(since=since, until=until)
    ga_prev = ga_fetch(since=since_prev, until=until_prev)
except Exception as e:
    print(f"  ⚠️  Google Ads failed: {e}")
    ga_data = None
    ga_prev = None

print(f"\nSummary:")
print(f"  FB Leads:    {data['totals']['unique']} unique")
print(f"  FB Spend:    €{data['cpl']['total_spend']}")
print(f"  FB CPL:      €{data['cpl']['overall']}")
if ga_data:
    print(f"  GA Leads:    {ga_data['totals']['leads']}")
    print(f"  GA Spend:    €{ga_data['totals']['spend']}")
    print(f"  GA CPL:      €{ga_data['totals']['cpl']}")
    total_leads = data['totals']['unique'] + ga_data['totals']['leads']
    total_spend = data['cpl']['total_spend'] + ga_data['totals']['spend']
    print(f"  TOTAL Leads: {total_leads}")
    print(f"  TOTAL Spend: €{round(total_spend,2)}")
    print(f"  TOTAL CPL:   €{round(total_spend/total_leads,2) if total_leads else 0}")
print(f"  Priority:    {data['priority_leads']} hot leads")
print(f"  Dupes:       {data['totals']['duplicates']} removed")

os.makedirs(os.path.join(os.path.dirname(__file__), "../data"), exist_ok=True)
with open(os.path.join(os.path.dirname(__file__), "../data/latest.json"), "w") as f:
    json.dump({k:v for k,v in data.items() if k != "_leads"}, f, indent=2)
print("\n💾 Saved to data/latest.json")

if args.dry_run:
    print("\n✅ Dry run complete — no Slack message or emails sent")
else:
    blocks = build_report(data, prev_data, ga_data, ga_prev)
    post_to_slack(blocks)
    if not args.no_email:
        send_all(data, prev_data, ga_data, ga_prev)
