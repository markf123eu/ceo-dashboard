import os, json, requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sys
sys.path.insert(0, os.path.dirname(__file__))
from facebook_leads import fetch_and_analyse, fetch_forms, fetch_leads, parse_fields, classify

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

SLACK_BOT_TOKEN      = os.getenv("SLACK_BOT_TOKEN")
SLACK_DAILY_CHANNEL  = os.getenv("SLACK_DAILY_CHANNEL_ID")
COMPANY_NAME         = os.getenv("COMPANY_NAME", "Company")
FB_GOAL              = 80
GA_GOAL              = 40

def _eur(value):
    return f"€{value:,.2f}" if value is not None else "N/A"

def _bar(value, total, width=8):
    if total == 0: return "░" * width
    filled = round((value / total) * width)
    return "█" * filled + "░" * (width - filled)

def _pct(value, total):
    return f"{round(value / total * 100)}%" if total else "0%"

def post_to_slack(blocks, channel):
    resp = requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json={"channel": channel, "text": "Daily Leads Report", "blocks": blocks, "unfurl_links": False})
    data = resp.json()
    if not data.get("ok"):
        print(f"❌ Slack error: {data.get('error')}")
        return False
    print(f"✅ Posted to Slack successfully")
    return True

def build_daily_report():
    # Get yesterday's leads
    until = datetime.utcnow().replace(hour=23, minute=59, second=59)
    since = until.replace(hour=0, minute=0, second=0)

    print(f"Fetching leads for {since.date()}...")
    data = fetch_and_analyse(since=since, until=until)

    # Fetch raw leads for full detail
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
            "full_name":  fields.get("full_name", "Unknown"),
            "phone":      fields.get("phone_number", ""),
            "eircode":    eircode,
            "timeline":   fields.get("when_are_you_looking_to_replace_your_boiler?", "unknown"),
            "campaign":   lead.get("campaign_name", "Unknown"),
            "platform":   lead.get("platform", "unknown"),
            "zone":       zone,
            "created":    lead.get("created_time", "")[:16].replace("T", " "),
        })

    t    = data["totals"]
    g    = data["geography"]
    tl   = data["timelines"]
    total = t["unique"]
    today_label = since.strftime("%A %d %b %Y")

    # Sort — hot leads first
    def sort_key(l):
        order = {"asap": 0, "within_1_month": 1, "within_3_months": 2, "unknown": 3}
        return order.get(l.get("timeline", "unknown"), 3)
    parsed_leads.sort(key=sort_key)

    hot   = [l for l in parsed_leads if l["timeline"] in ("asap", "within_1_month")]
    other = [l for l in parsed_leads if l["timeline"] not in ("asap", "within_1_month")]

    dublin_total = g["within_10km"] + g["band_10_20km"]

    # Build lead lines
    def lead_line(l):
        timeline = l["timeline"].replace("_", " ").title()
        zone_icon = "🎯" if l["zone"] == "within_10km" else "📍" if l["zone"] == "10_20km" else "🗺️" if l["zone"] == "outside_20km" else "❓"
        return (f"*{l['full_name']}*  {zone_icon} `{l['eircode'] or 'No eircode'}`\n"
                f"  📞 {l['phone'] or 'No phone'}  |  ⏰ _{timeline}_  |  📣 _{l['campaign'][:30]}_")

    hot_lines   = "\n\n".join(lead_line(l) for l in hot[:20])   or "_No hot leads today_"
    other_lines = "\n\n".join(lead_line(l) for l in other[:20]) or "_No other leads today_"

    blocks = [
        {"type":"header","text":{"type":"plain_text","text":f"📋 Daily Leads Report — {today_label}"}},
        {"type":"divider"},

        # Summary
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*👥 Total Leads*\n`{total}` unique"},
            {"type":"mrkdwn","text":f"*🔥 Hot Leads*\n`{len(hot)}` (ASAP + within 1 month)"},
            {"type":"mrkdwn","text":f"*✅ Dublin Leads*\n`{dublin_total}` ({_pct(dublin_total, total)})"},
            {"type":"mrkdwn","text":f"*🗺️ Outside Dublin*\n`{g['outside_20km']}` ({_pct(g['outside_20km'], total)})"},
        ]},
        {"type":"divider"},

        # Geographic breakdown
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*📍 Geographic Breakdown*\n"
            f"🎯 Core Dublin (within 10km)  {_bar(g['within_10km'],total)}  `{g['within_10km']}` ({_pct(g['within_10km'],total)})\n"
            f"📍 Greater Dublin (10–20km)   {_bar(g['band_10_20km'],total)}  `{g['band_10_20km']}` ({_pct(g['band_10_20km'],total)})\n"
            f"🗺️  Outside Dublin             {_bar(g['outside_20km'],total)}  `{g['outside_20km']}` ({_pct(g['outside_20km'],total)})\n"
            f"❓ Unknown                    {_bar(g['unknown'],total)}  `{g['unknown']}` ({_pct(g['unknown'],total)})"
        )}},
        {"type":"divider"},

        # Purchase intent
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*⏰ Purchase Intent*\n" +
            "\n".join(f"`{k.replace('_',' ').title()}`: {v} leads" for k,v in list(tl.items())[:5])
        )}},
        {"type":"divider"},

        # Hot leads
        {"type":"section","text":{"type":"mrkdwn","text":f"*🔥 Hot Leads — ASAP & Within 1 Month ({len(hot)})*"}},
    ]

    if hot:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":hot_lines}})

    blocks += [
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":f"*👥 All Other Leads ({len(other)})*"}},
    ]

    if other:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":other_lines}})

    if t["duplicates"] > 0:
        blocks += [
            {"type":"divider"},
            {"type":"section","text":{"type":"mrkdwn","text":f"⚠️ *{t['duplicates']} duplicate leads removed*"}},
        ]

    blocks.append({"type":"context","elements":[{"type":"mrkdwn",
        "text":f"{COMPANY_NAME} Daily Report • {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC"}]})

    return blocks

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    blocks = build_daily_report()

    if args.dry_run:
        print("✅ Dry run complete — no Slack message sent")
    else:
        post_to_slack(blocks, SLACK_DAILY_CHANNEL)
