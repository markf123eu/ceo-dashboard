import sys, os, json, argparse
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from week_utils import get_last_week, get_week_before, week_label
from facebook_leads import fetch_and_analyse, fetch_forms, fetch_leads, parse_fields, classify
from google_ads import fetch_and_analyse as ga_fetch
from slack_reporter import build_report, post_to_slack
from email_reporter import send_all
from hubspot_pipeline import fetch_hp_qualified, fetch_new_contacts_by_type
from jobber_surveys import fetch_site_surveys

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--no-email", action="store_true")
args = parser.parse_args()

print("\n=== CEO Dashboard — Weekly Report ===\n")

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

HIRING_KEYWORDS = ["hiring", "recruit", "job", "career", "vacancy", "staff"]

def is_hp_campaign(name):
    return "hp" in (name or "").lower()

def is_hiring_campaign(name):
    return any(k in (name or "").lower() for k in HIRING_KEYWORDS)

parsed_leads = []
for lead in all_leads:
    fields = parse_fields(lead.get("field_data", []))
    eircode = (fields.get("what_is_your_eircode(dublin_only)?") or
               fields.get("eircode") or fields.get("postcode") or "")
    dist, zone = classify(eircode)
    campaign = lead.get("campaign_name", "Unknown") or "Unknown"
    parsed_leads.append({
        "full_name": fields.get("full_name", "Unknown"),
        "phone": fields.get("phone_number", ""),
        "eircode": eircode,
        "timeline": fields.get("when_are_you_looking_to_replace_your_boiler?", "unknown"),
        "zone": zone,
        "campaign": campaign,
        "is_hp": is_hp_campaign(campaign),
        "is_hiring": is_hiring_campaign(campaign),
    })

data["_leads"] = parsed_leads

# Split campaign spend by type
fb_boiler_spend = 0.0
fb_hp_spend = 0.0
fb_boiler_leads = 0
fb_hp_leads = 0

for camp, info in data["cpl"]["by_campaign"].items():
    if is_hiring_campaign(camp):
        continue
    if is_hp_campaign(camp):
        fb_hp_spend += info["spend"]
        fb_hp_leads += info["leads"]
    else:
        fb_boiler_spend += info["spend"]
        fb_boiler_leads += info["leads"]

fb_boiler_cpl = round(fb_boiler_spend / fb_boiler_leads, 2) if fb_boiler_leads else None
fb_hp_cpl = round(fb_hp_spend / fb_hp_leads, 2) if fb_hp_leads else None

print(f"\nFacebook Split:")
print(f"  Boiler: {fb_boiler_leads} leads | €{round(fb_boiler_spend,2)} spend | CPL: €{fb_boiler_cpl}")
print(f"  HP:     {fb_hp_leads} leads | €{round(fb_hp_spend,2)} spend | CPL: €{fb_hp_cpl}")

# Facebook last week for comparison
print("\nFetching previous week for comparison...")
prev_data = fetch_and_analyse(since=since_prev, until=until_prev)

# Google Ads
print("Fetching Google Ads data...")
try:
    ga_data = ga_fetch(since=since, until=until)
    ga_prev = ga_fetch(since=since_prev, until=until_prev)

    # Split Google by HP vs boiler
    ga_boiler_spend = 0.0
    ga_hp_spend = 0.0
    ga_boiler_leads = 0
    ga_hp_leads = 0
    for camp, info in ga_data["campaigns"].items():
        if is_hp_campaign(camp) or "heat pump" in camp.lower():
            ga_hp_spend += info["spend"]
            ga_hp_leads += info["leads"]
        else:
            ga_boiler_spend += info["spend"]
            ga_boiler_leads += info["leads"]

    ga_boiler_cpl = round(ga_boiler_spend / ga_boiler_leads, 2) if ga_boiler_leads else None
    ga_hp_cpl = round(ga_hp_spend / ga_hp_leads, 2) if ga_hp_leads else None

    print(f"\nGoogle Ads Split:")
    print(f"  Boiler: {ga_boiler_leads} leads | €{round(ga_boiler_spend,2)} spend | CPL: €{ga_boiler_cpl}")
    print(f"  HP:     {ga_hp_leads} leads | €{round(ga_hp_spend,2)} spend | CPL: €{ga_hp_cpl}")

except Exception as e:
    print(f"  ⚠️  Google Ads failed: {e}")
    ga_data = None
    ga_prev = None
    ga_boiler_spend = ga_hp_spend = ga_boiler_leads = ga_hp_leads = 0
    ga_boiler_cpl = ga_hp_cpl = None

# Jobber site surveys
print("\nFetching Jobber site surveys...")
try:
    surveys_data = fetch_site_surveys(since, until)
    survey_count = surveys_data["count"]
    print(f"  Site surveys booked: {survey_count}")
except Exception as e:
    print(f"  ⚠️  Jobber surveys failed: {e}")
    surveys_data = None
    survey_count = None

# HubSpot HP qualified
print("Fetching HubSpot HP qualified leads...")
try:
    hp_qualified = fetch_hp_qualified(since, until)
    hp_qualified_count = hp_qualified["count"]
    print(f"  HP qualified: {hp_qualified_count}")
except Exception as e:
    print(f"  ⚠️  HubSpot HP qualified failed: {e}")
    hp_qualified = None
    hp_qualified_count = None

# Combined totals
total_boiler_leads = fb_boiler_leads + ga_boiler_leads
total_hp_leads = fb_hp_leads + ga_hp_leads
total_boiler_spend = round(fb_boiler_spend + ga_boiler_spend, 2)
total_hp_spend = round(fb_hp_spend + ga_hp_spend, 2)

print(f"\n=== Summary ===")
print(f"  BOILER Leads:  {total_boiler_leads} | Spend: €{total_boiler_spend} | Surveys: {survey_count}")
print(f"  HP Leads:      {total_hp_leads} | Spend: €{total_hp_spend} | Qualified: {hp_qualified_count}")
print(f"  TOTAL Leads:   {total_boiler_leads + total_hp_leads}")
print(f"  TOTAL Spend:   €{round(total_boiler_spend + total_hp_spend, 2)}")
print(f"  Priority:      {data['priority_leads']} hot leads")
print(f"  Dupes:         {data['totals']['duplicates']} removed")

# Save split data
split_data = {
    "fb_boiler": {"leads": fb_boiler_leads, "spend": round(fb_boiler_spend,2), "cpl": fb_boiler_cpl},
    "fb_hp": {"leads": fb_hp_leads, "spend": round(fb_hp_spend,2), "cpl": fb_hp_cpl},
    "ga_boiler": {"leads": ga_boiler_leads, "spend": round(ga_boiler_spend,2), "cpl": ga_boiler_cpl},
    "ga_hp": {"leads": ga_hp_leads, "spend": round(ga_hp_spend,2), "cpl": ga_hp_cpl},
    "survey_count": survey_count,
    "hp_qualified_count": hp_qualified_count,
}
data["split"] = split_data

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
