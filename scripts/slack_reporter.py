import os, json, requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Company")
WEEKLY_GOAL = 120

def _bar(value, total, width=10):
    if total == 0: return "░" * width
    filled = round((value / total) * width)
    return "█" * filled + "░" * (width - filled)

def _pct(value, total):
    return f"{round(value / total * 100)}%" if total else "0%"

def _eur(value):
    return f"€{value:,.2f}" if value is not None else "N/A"

def _day_name(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%A")
    except:
        return date_str

def _week_label(period):
    try:
        start = datetime.strptime(period["from"], "%Y-%m-%d")
        end   = datetime.strptime(period["to"],   "%Y-%m-%d")
        return f"Week of {start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    except:
        return f"{period['from']} to {period['to']}"

def _wow(curr, prev, prefix=""):
    if prev is None or curr is None: return ""
    diff = curr - prev
    if diff > 0: return f"📈 {prefix}+{diff} vs last week"
    if diff < 0: return f"📉 {prefix}{diff} vs last week"
    return "➡️ Same as last week"

def _wow_eur(curr, prev):
    if prev is None or curr is None: return ""
    diff = round(curr - prev, 2)
    if diff > 0: return f"📈 +€{diff} vs last week"
    if diff < 0: return f"📉 €{abs(diff)} vs last week"
    return "➡️ Same as last week"

def _goal_bar(current, goal, width=10):
    filled = min(round((current / goal) * width), width)
    return "█" * filled + "░" * (width - filled)

def build_report(data, prev_data=None, ga_data=None, ga_prev=None):
    t      = data["totals"]
    g      = data["geography"]
    plat   = data["platforms"]
    tl     = data["timelines"]
    daily  = data["daily_volume"]
    cpl    = data["cpl"]
    hiring = data.get("hiring", {})
    total  = t["unique"]
    asap   = tl.get("asap", 0)
    within_1m = tl.get("within_1_month", 0)
    fb     = plat.get("fb", 0)
    ig     = plat.get("ig", 0)
    week_label = _week_label(data["period"])

    prev_total  = prev_data["totals"]["unique"]          if prev_data else None
    prev_cpl    = prev_data["cpl"]["overall"]            if prev_data else None
    prev_asap   = prev_data["timelines"].get("asap", 0)  if prev_data else None

    ga_leads      = ga_data["totals"]["leads"]   if ga_data else 0
    ga_spend      = ga_data["totals"]["spend"]   if ga_data else 0
    ga_cpl        = ga_data["totals"]["cpl"]     if ga_data else None
    ga_ctr        = ga_data["totals"]["ctr"]     if ga_data else None
    ga_prev_leads = ga_prev["totals"]["leads"]   if ga_prev else None
    ga_prev_cpl   = ga_prev["totals"]["cpl"]     if ga_prev else None

    combined_leads = total + ga_leads
    combined_spend = round(cpl["total_spend"] + ga_spend, 2)
    combined_cpl   = round(combined_spend / combined_leads, 2) if combined_leads else None
    prev_combined  = (prev_total or 0) + (ga_prev_leads or 0)

    # Goal progress
    goal_pct     = round(combined_leads / WEEKLY_GOAL * 100)
    prev_goal_pct = round(prev_combined / WEEKLY_GOAL * 100) if prev_combined else 0
    leads_to_go  = max(WEEKLY_GOAL - combined_leads, 0)
    goal_bar     = _goal_bar(combined_leads, WEEKLY_GOAL)
    if combined_leads >= WEEKLY_GOAL:
        goal_status = "✅ Goal achieved!"
    elif goal_pct >= 80:
        goal_status = f"🔶 {leads_to_go} leads to go"
    else:
        goal_status = f"🔴 {leads_to_go} leads to go"

    # Daily volume
    max_daily = max(daily.values()) if daily else 1
    daily_lines = []
    for date_str, count in daily.items():
        day = _day_name(date_str)
        bar = _bar(count, max_daily, 8)
        daily_lines.append(f"`{day:<9}` {bar}  *{count}*")
    daily_text = "\n".join(daily_lines)

    # Hot leads
    hot_leads = [l for l in data.get("_leads", [])
                 if l.get("timeline") in ("asap", "within_1_month")]
    if hot_leads:
        hot_lines = "\n".join(
            f"  🔥 *{l['full_name']}*  `{l.get('eircode','')}` — _{l['timeline'].replace('_',' ')}_"
            for l in hot_leads[:15])
        if len(hot_leads) > 15:
            hot_lines += f"\n  _...and {len(hot_leads)-15} more_"
    else:
        hot_lines = "_No hot leads this week_"

    # Geography
    dublin_total  = g["within_10km"] + g["band_10_20km"]
    outside_total = g["outside_20km"]
    unknown_total = g["unknown"]

    # FB campaigns
    fb_camp_lines = []
    for camp, info in sorted(cpl["by_campaign"].items(), key=lambda x: x[1]["spend"], reverse=True)[:5]:
        short = camp.replace("_Dublin_ACB","").replace("_Dublin","")[:35]
        fb_camp_lines.append(f"  `{short}`\n  {info['leads']} leads | {_eur(info['spend'])} spend | *{_eur(info['cpl'])} CPL*")
    fb_camp_text = "\n".join(fb_camp_lines)

    # GA campaigns
    ga_camp_lines = []
    if ga_data:
        for camp, info in list(ga_data["campaigns"].items())[:5]:
            ga_camp_lines.append(f"  `{camp[:35]}`\n  {info['leads']} leads | {_eur(info['spend'])} spend | *{_eur(info['cpl'])} CPL* | CTR: {info['ctr']}%")
    ga_camp_text = "\n".join(ga_camp_lines) if ga_camp_lines else "_No Google Ads data_"

    blocks = [
        # FACEBOOK
        {"type":"header","text":{"type":"plain_text","text":f"📘 Facebook Report — {week_label}"}},
        {"type":"divider"},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Total Leads*\n`{total}` unique  _({t['duplicates']} dupes removed)_\n_{_wow(total, prev_total)}_"},
            {"type":"mrkdwn","text":f"*CPL*\n`{_eur(cpl['overall'])}`\n_{_wow_eur(cpl['overall'], prev_cpl)}_"},
            {"type":"mrkdwn","text":f"*Total Spend*\n`{_eur(cpl['total_spend'])}`"},
            {"type":"mrkdwn","text":f"*Hot Leads*\n`{asap + within_1m}` within 1 month\n_{_wow(asap, prev_asap, 'ASAP ')}_"},
        ]},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":f"*📅 Daily Volume*\n{daily_text}"}},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*📍 Geographic Breakdown*\n"
            f"🎯 Core Dublin (within 10km)   {_bar(g['within_10km'],total)}  `{g['within_10km']}` ({_pct(g['within_10km'],total)})\n"
            f"📍 Greater Dublin (10–20km)    {_bar(g['band_10_20km'],total)}  `{g['band_10_20km']}` ({_pct(g['band_10_20km'],total)})\n"
            f"──────────────────────────────────────────\n"
            f"✅ Total Dublin                {_bar(dublin_total,total)}  `{dublin_total}` ({_pct(dublin_total,total)})\n"
            f"🗺️  Outside Dublin              {_bar(outside_total,total)}  `{outside_total}` ({_pct(outside_total,total)})\n"
            f"❓ Unknown eircode             {_bar(unknown_total,total)}  `{unknown_total}` ({_pct(unknown_total,total)})"
        )}},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":f"*🔥 Hot Leads — ASAP & Within 1 Month*\n{hot_lines}"}},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":f"*📣 Facebook Campaigns*\n{fb_camp_text}"}},
        {"type":"divider"},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":"*⏰ Purchase Intent*\n" +
                "\n".join(f"`{k.replace('_',' ')}`: {v}" for k,v in list(tl.items())[:4])},
            {"type":"mrkdwn","text":f"*📱 Platform*\nFacebook `{fb}` ({_pct(fb,total)})\nInstagram `{ig}` ({_pct(ig,total)})"},
        ]},

        # GOOGLE ADS
        {"type":"header","text":{"type":"plain_text","text":f"🔍 Google Ads Report — {week_label}"}},
        {"type":"divider"},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Total Leads*\n`{ga_leads}`\n_{_wow(ga_leads, ga_prev_leads)}_"},
            {"type":"mrkdwn","text":f"*CPL*\n`{_eur(ga_cpl)}`\n_{_wow_eur(ga_cpl, ga_prev_cpl)}_"},
            {"type":"mrkdwn","text":f"*Total Spend*\n`{_eur(ga_spend)}`"},
            {"type":"mrkdwn","text":f"*CTR*\n`{ga_ctr}%`" if ga_ctr else "*CTR*\n`N/A`"},
        ]},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":f"*🔍 Google Campaigns*\n{ga_camp_text}"}},

        # COMBINED SUMMARY
        {"type":"header","text":{"type":"plain_text","text":f"📊 Combined Summary — {week_label}"}},
        {"type":"divider"},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Total Leads*\n`{combined_leads}`\n_{_wow(combined_leads, prev_combined)}_"},
            {"type":"mrkdwn","text":f"*Blended CPL*\n`{_eur(combined_cpl)}`\n_{_wow_eur(combined_cpl, ga_prev_cpl)}_"},
            {"type":"mrkdwn","text":f"*Total Spend*\n`{_eur(combined_spend)}`"},
            {"type":"mrkdwn","text":f"*Priority Leads*\n`{data['priority_leads']}` hot leads"},
        ]},
        {"type":"divider"},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Facebook*\n`{total}` leads | `{_eur(cpl['total_spend'])}` | `{_eur(cpl['overall'])}` CPL\n_{_wow(total, prev_total)}_"},
            {"type":"mrkdwn","text":f"*Google*\n`{ga_leads}` leads | `{_eur(ga_spend)}` | `{_eur(ga_cpl)}` CPL\n_{_wow(ga_leads, ga_prev_leads)}_"},
        ]},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*🎯 Weekly Goal: {WEEKLY_GOAL} Leads*\n"
            f"{goal_bar}  `{goal_pct}%` of goal\n"
            f"This week: `{combined_leads}` leads  {goal_status}\n"
            f"Last week: `{prev_combined}` leads  (`{prev_goal_pct}%` of goal)\n"
            f"_{_wow(combined_leads, prev_combined)}_"
        )}},
    ]

    # Hiring
    if hiring.get("leads", 0) > 0 or hiring.get("spend", 0) > 0:
        hiring_cpl = round(hiring["spend"] / hiring["leads"], 2) if hiring.get("leads") else None
        blocks += [
            {"type":"divider"},
            {"type":"section","text":{"type":"mrkdwn","text":(
                f"*👷 Hiring Campaign (Not included in sales numbers)*\n"
                f"Leads: `{hiring['leads']}` | Spend: `{_eur(hiring['spend'])}` | CPL: `{_eur(hiring_cpl)}`"
            )}},
        ]

    # Duplicates
    dupes = data.get("duplicate_contacts", [])
    if dupes:
        names = ", ".join(d["name"] for d in dupes[:5])
        if len(dupes) > 5: names += f" +{len(dupes)-5} more"
        blocks += [
            {"type":"divider"},
            {"type":"section","text":{"type":"mrkdwn","text":f"⚠️ *{len(dupes)} duplicate leads removed:*\n_{names}_"}},
        ]

    blocks.append({"type":"context","elements":[{"type":"mrkdwn",
        "text":f"{COMPANY_NAME} CEO Dashboard • {datetime.utcnow().strftime('%a %d %b %Y %H:%M')} UTC"}]})
    return blocks

def post_to_slack(blocks):
    resp = requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization":f"Bearer {SLACK_BOT_TOKEN}","Content-Type":"application/json"},
        json={"channel":SLACK_CHANNEL_ID,"text":"Weekly Lead Report","blocks":blocks,"unfurl_links":False})
    data = resp.json()
    if not data.get("ok"):
        print(f"❌ Slack error: {data.get('error')}")
        return False
    print(f"✅ Posted to Slack successfully")
    return True

if __name__ == "__main__":
    print("Slack reporter ready")
