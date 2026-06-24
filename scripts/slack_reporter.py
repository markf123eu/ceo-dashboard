import os, json, requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

SLACK_BOT_TOKEN  = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
COMPANY_NAME     = os.getenv("COMPANY_NAME", "Company")

# Weekly goals
BOILER_WEEKLY_LEAD_GOAL     = 100   # enough to fill 45 surveys at 45% conversion
BOILER_SURVEY_CAPACITY_MIN  = 40
BOILER_SURVEY_CAPACITY_MAX  = 45
BOILER_LEAD_TO_SURVEY_RATE  = 0.45
HP_WEEKLY_LEAD_GOAL         = 60
HP_WEEKLY_QUALIFIED_GOAL    = 20

# Monthly budgets
FB_BOILER_MONTHLY_BUDGET    = 10320
GA_BOILER_MONTHLY_BUDGET    = 5160
FB_HP_MONTHLY_BUDGET        = 4800
GA_HP_MONTHLY_BUDGET        = 2580

# Weekly budgets
FB_BOILER_WEEKLY_BUDGET     = round(FB_BOILER_MONTHLY_BUDGET / 4.3)
GA_BOILER_WEEKLY_BUDGET     = round(GA_BOILER_MONTHLY_BUDGET / 4.3)
FB_HP_WEEKLY_BUDGET         = round(FB_HP_MONTHLY_BUDGET / 4.3)
GA_HP_WEEKLY_BUDGET         = round(GA_HP_MONTHLY_BUDGET / 4.3)

# Revenue & budget model
CURRENT_MONTHLY_REVENUE     = 200000
VAT_RATE                    = 0.135
REVENUE_NET                 = round(CURRENT_MONTHLY_REVENUE / (1 + VAT_RATE))
MARKETING_BUDGET_PCT        = 0.05
MONTHLY_MARKETING_BUDGET    = round(REVENUE_NET * MARKETING_BUDGET_PCT)
WEEKLY_MARKETING_BUDGET     = round(MONTHLY_MARKETING_BUDGET / 4.3)

# Scaling model — surveys per week at different capacities
SCALING_MODEL = [
    {"surveys": 45,  "leads": 100,  "monthly_spend": 8500,  "label": "Current capacity (1 salesperson)"},
    {"surveys": 60,  "leads": 133,  "monthly_spend": 11000, "label": "Near full — plan for 2nd salesperson"},
    {"surveys": 80,  "leads": 178,  "monthly_spend": 15000, "label": "2 salespeople at capacity"},
    {"surveys": 100, "leads": 222,  "monthly_spend": 18500, "label": "Scale target"},
]

def _bar(value, total, width=10):
    if total == 0: return "░" * width
    filled = round((value / total) * width)
    return "█" * filled + "░" * (width - filled)

def _goal_bar(value, goal, width=10):
    if goal == 0: return "░" * width
    filled = min(round((value / goal) * width), width)
    return "█" * filled + "░" * (width - filled)

def _pct(value, total):
    return f"{round(value / total * 100)}%" if total else "0%"

def _eur(value):
    return f"€{value:,.2f}" if value is not None else "N/A"

def _eur_int(value):
    return f"€{int(value):,}" if value is not None else "N/A"

def _goal_status(value, goal):
    if value is None: return "⚪ No data"
    pct = round(value / goal * 100) if goal else 0
    if value >= goal: return f"✅ {value}/{goal}"
    elif pct >= 70:   return f"🟡 {value}/{goal} ({pct}%)"
    else:             return f"🔴 {value}/{goal} ({pct}%)"

def _spend_status(spend, budget):
    if spend is None or budget == 0: return "⚪ No data"
    pct = round(spend / budget * 100)
    if pct > 110:   return f"🔴 Over budget ({pct}%)"
    elif pct >= 85: return f"✅ On track ({pct}%)"
    elif pct >= 60: return f"🟡 Under budget ({pct}%)"
    else:           return f"🔴 Well under budget ({pct}%)"

def _capacity_status(surveys):
    if surveys is None: return "⚪ No survey data"
    if surveys >= BOILER_SURVEY_CAPACITY_MAX:
        return f"🔴 At capacity — consider 2nd salesperson ({surveys}/{BOILER_SURVEY_CAPACITY_MAX})"
    elif surveys >= BOILER_SURVEY_CAPACITY_MIN:
        return f"✅ Full capacity ({surveys}/{BOILER_SURVEY_CAPACITY_MAX})"
    elif surveys >= round(BOILER_SURVEY_CAPACITY_MIN * 0.7):
        return f"🟡 Partial capacity ({surveys}/{BOILER_SURVEY_CAPACITY_MAX})"
    else:
        return f"🔴 Under capacity ({surveys}/{BOILER_SURVEY_CAPACITY_MAX})"

def _wow(curr, prev):
    if prev is None or curr is None: return ""
    diff = curr - prev
    if diff > 0: return f"📈 +{diff} vs last week"
    if diff < 0: return f"📉 {diff} vs last week"
    return "➡️ Same as last week"

def _wow_eur(curr, prev):
    if prev is None or curr is None: return ""
    diff = round(curr - prev, 2)
    if diff > 0: return f"📈 +€{diff} vs last week"
    if diff < 0: return f"📉 -€{abs(diff)} vs last week"
    return "➡️ Same as last week"

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

def is_hp_campaign(name):
    return "hp" in (name or "").lower()

def is_hiring_campaign(name):
    keywords = ["hiring", "recruit", "job", "career", "vacancy", "staff"]
    return any(k in (name or "").lower() for k in keywords)

def build_report(data, prev_data=None, ga_data=None, ga_prev=None):
    t      = data["totals"]
    g      = data["geography"]
    tl     = data["timelines"]
    daily  = data["daily_volume"]
    cpl    = data["cpl"]
    split  = data.get("split", {})
    week_label = _week_label(data["period"])

    # Split data
    fb_boiler = split.get("fb_boiler", {})
    fb_hp     = split.get("fb_hp", {})
    ga_boiler = split.get("ga_boiler", {})
    ga_hp     = split.get("ga_hp", {})
    survey_count       = split.get("survey_count")
    hp_qualified_count = split.get("hp_qualified_count")

    total_boiler_leads = (fb_boiler.get("leads", 0) or 0) + (ga_boiler.get("leads", 0) or 0)
    total_hp_leads     = (fb_hp.get("leads", 0) or 0) + (ga_hp.get("leads", 0) or 0)
    total_boiler_spend = round((fb_boiler.get("spend", 0) or 0) + (ga_boiler.get("spend", 0) or 0), 2)
    total_hp_spend     = round((fb_hp.get("spend", 0) or 0) + (ga_hp.get("spend", 0) or 0), 2)
    total_boiler_cpl   = round(total_boiler_spend / total_boiler_leads, 2) if total_boiler_leads else None
    total_hp_cpl       = round(total_hp_spend / total_hp_leads, 2) if total_hp_leads else None
    combined_spend     = round(total_boiler_spend + total_hp_spend, 2)

    # Actual lead → survey conversion rate
    actual_conversion = round(survey_count / total_boiler_leads * 100, 1) if (survey_count and total_boiler_leads) else None

    # Previous week
    prev_total    = prev_data["totals"]["unique"] if prev_data else None
    ga_prev_leads = ga_prev["totals"]["leads"]    if ga_prev else None

    # Google totals
    ga_leads = ga_data["totals"]["leads"] if ga_data else 0
    ga_spend = ga_data["totals"]["spend"] if ga_data else 0
    combined_leads = t["unique"] + ga_leads
    combined_cpl   = round(combined_spend / combined_leads, 2) if combined_leads else None

    # Daily volume
    max_daily = max(daily.values()) if daily else 1
    daily_lines = []
    for date_str, count in daily.items():
        day = _day_name(date_str)
        bar = _bar(count, max_daily, 8)
        daily_lines.append(f"`{day:<9}` {bar}  *{count}*")
    daily_text = "\n".join(daily_lines)

    # Hot leads
    hot_leads  = [l for l in data.get("_leads", []) if l.get("timeline") in ("asap", "within_1_month") and not l.get("is_hiring")]
    hot_boiler = [l for l in hot_leads if not l.get("is_hp")]
    hot_hp     = [l for l in hot_leads if l.get("is_hp")]

    def hot_line(l):
        return (f"  🔥 *{l['full_name']}*  `{l.get('eircode','')}` — "
                f"_{l['timeline'].replace('_',' ')}_ — _{l.get('campaign','')[:30]}_")

    hot_boiler_text = "\n".join(hot_line(l) for l in hot_boiler[:10]) or "_No hot boiler leads_"
    hot_hp_text     = "\n".join(hot_line(l) for l in hot_hp[:10]) or "_No hot HP leads_"

    # Geography
    total = t["unique"]
    dublin_total = g["within_10km"] + g["band_10_20km"]

    # FB boiler campaigns
    fb_boiler_camps = []
    for camp, info in sorted(cpl["by_campaign"].items(), key=lambda x: x[1]["spend"], reverse=True):
        if is_hiring_campaign(camp) or is_hp_campaign(camp): continue
        short = camp.replace("_Dublin_ACB","").replace("_Dublin","")[:35]
        fb_boiler_camps.append(f"  `{short}`\n  {info['leads']} leads | {_eur(info['spend'])} | *{_eur(info['cpl'])} CPL*")
    fb_boiler_camp_text = "\n".join(fb_boiler_camps[:5]) or "_No data_"

    # FB HP campaigns
    fb_hp_camps = []
    for camp, info in sorted(cpl["by_campaign"].items(), key=lambda x: x[1]["spend"], reverse=True):
        if not is_hp_campaign(camp): continue
        fb_hp_camps.append(f"  `{camp[:35]}`\n  {info['leads']} leads | {_eur(info['spend'])} | *{_eur(info['cpl'])} CPL*")
    fb_hp_camp_text = "\n".join(fb_hp_camps) or "_No HP campaigns_"

    # GA campaigns split
    ga_boiler_camps = []
    ga_hp_camps = []
    if ga_data:
        for camp, info in ga_data["campaigns"].items():
            line = f"  `{camp[:35]}`\n  {info['leads']} leads | {_eur(info['spend'])} | *{_eur(info['cpl'])} CPL*"
            if is_hp_campaign(camp) or "heat pump" in camp.lower():
                ga_hp_camps.append(line)
            else:
                ga_boiler_camps.append(line)
    ga_boiler_camp_text = "\n".join(ga_boiler_camps) or "_No data_"
    ga_hp_camp_text     = "\n".join(ga_hp_camps) or "_No HP Google campaigns_"

    # Budget model
    boiler_weekly_budget = FB_BOILER_WEEKLY_BUDGET + GA_BOILER_WEEKLY_BUDGET
    hp_weekly_budget     = FB_HP_WEEKLY_BUDGET + GA_HP_WEEKLY_BUDGET

    # Scaling table text
    scaling_lines = []
    for row in SCALING_MODEL:
        marker = "👉 " if row["surveys"] == BOILER_SURVEY_CAPACITY_MAX else "    "
        scaling_lines.append(
            f"{marker}`{row['surveys']} surveys/wk`  →  "
            f"{row['leads']} leads/wk  |  "
            f"{_eur_int(row['monthly_spend'])}/month  |  "
            f"_{row['label']}_"
        )
    scaling_text = "\n".join(scaling_lines)

    blocks = [
        # ── OVERVIEW ──
        {"type":"header","text":{"type":"plain_text","text":f"📊 Weekly CEO Dashboard — {week_label}"}},
        {"type":"divider"},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":(
                f"*🔥 Boiler Leads*\n"
                f"{_goal_bar(total_boiler_leads, BOILER_WEEKLY_LEAD_GOAL)}  `{total_boiler_leads}/{BOILER_WEEKLY_LEAD_GOAL}`\n"
                f"_{_goal_status(total_boiler_leads, BOILER_WEEKLY_LEAD_GOAL)}_\n"
                f"_{_wow(total_boiler_leads, prev_total)}_"
            )},
            {"type":"mrkdwn","text":(
                f"*♨️ Heat Pump Leads*\n"
                f"{_goal_bar(total_hp_leads, HP_WEEKLY_LEAD_GOAL)}  `{total_hp_leads}/{HP_WEEKLY_LEAD_GOAL}`\n"
                f"_{_goal_status(total_hp_leads, HP_WEEKLY_LEAD_GOAL)}_"
            )},
        ]},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":(
                f"*🏠 Site Surveys Booked*\n"
                f"{_goal_bar(survey_count or 0, BOILER_SURVEY_CAPACITY_MAX)}  `{survey_count if survey_count is not None else 'N/A'}/{BOILER_SURVEY_CAPACITY_MAX}`\n"
                f"_{_capacity_status(survey_count)}_"
            )},
            {"type":"mrkdwn","text":(
                f"*✅ HP Qualified (HubSpot)*\n"
                f"{_goal_bar(hp_qualified_count or 0, HP_WEEKLY_QUALIFIED_GOAL)}  `{hp_qualified_count if hp_qualified_count is not None else 'N/A'}/{HP_WEEKLY_QUALIFIED_GOAL}`\n"
                f"_{_goal_status(hp_qualified_count or 0, HP_WEEKLY_QUALIFIED_GOAL)}_"
            )},
        ]},
        {"type":"divider"},

        # ── BOILER SECTION ──
        {"type":"header","text":{"type":"plain_text","text":"🔥 Boiler Performance"}},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Facebook*\n`{fb_boiler.get('leads',0)}` leads | {_eur(fb_boiler.get('spend'))} | *{_eur(fb_boiler.get('cpl'))} CPL*\n_{_spend_status(fb_boiler.get('spend'), FB_BOILER_WEEKLY_BUDGET)}_"},
            {"type":"mrkdwn","text":f"*Google*\n`{ga_boiler.get('leads',0)}` leads | {_eur(ga_boiler.get('spend'))} | *{_eur(ga_boiler.get('cpl'))} CPL*\n_{_spend_status(ga_boiler.get('spend'), GA_BOILER_WEEKLY_BUDGET)}_"},
        ]},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Combined Boiler*\n`{total_boiler_leads}` leads | {_eur(total_boiler_spend)} | *{_eur(total_boiler_cpl)} CPL*"},
            {"type":"mrkdwn","text":f"*Weekly Budget*\n{_eur(total_boiler_spend)} / {_eur(boiler_weekly_budget)}\n_{_spend_status(total_boiler_spend, boiler_weekly_budget)}_"},
        ]},
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*🔄 Lead → Survey Conversion*\n"
            f"Boiler leads this week: `{total_boiler_leads}`\n"
            f"Site surveys booked: `{survey_count if survey_count is not None else 'N/A'}`\n"
            f"Actual conversion rate: `{actual_conversion}%` _(target: {round(BOILER_LEAD_TO_SURVEY_RATE*100)}%)_"
        )}},
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*📍 Geography*\n"
            f"🎯 Core Dublin (within 10km)  {_bar(g['within_10km'],total)}  `{g['within_10km']}` ({_pct(g['within_10km'],total)})\n"
            f"📍 Greater Dublin (10–20km)   {_bar(g['band_10_20km'],total)}  `{g['band_10_20km']}` ({_pct(g['band_10_20km'],total)})\n"
            f"🗺️  Outside Dublin             {_bar(g['outside_20km'],total)}  `{g['outside_20km']}` ({_pct(g['outside_20km'],total)})\n"
            f"❓ Unknown eircode            {_bar(g['unknown'],total)}  `{g['unknown']}` ({_pct(g['unknown'],total)})"
        )}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*📅 Daily Volume*\n{daily_text}"}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*📣 FB Boiler Campaigns*\n{fb_boiler_camp_text}"}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*🔍 Google Boiler Campaigns*\n{ga_boiler_camp_text}"}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*🔥 Hot Boiler Leads*\n{hot_boiler_text}"}},
        {"type":"divider"},

        # ── HEAT PUMP SECTION ──
        {"type":"header","text":{"type":"plain_text","text":"♨️ Heat Pump Performance"}},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Facebook HP*\n`{fb_hp.get('leads',0)}` leads | {_eur(fb_hp.get('spend'))} | *{_eur(fb_hp.get('cpl'))} CPL*\n_{_spend_status(fb_hp.get('spend'), FB_HP_WEEKLY_BUDGET)}_"},
            {"type":"mrkdwn","text":f"*Google HP*\n`{ga_hp.get('leads',0)}` leads | {_eur(ga_hp.get('spend'))} | *{_eur(ga_hp.get('cpl'))} CPL*\n_{_spend_status(ga_hp.get('spend'), GA_HP_WEEKLY_BUDGET)}_"},
        ]},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Combined HP*\n`{total_hp_leads}` leads | {_eur(total_hp_spend)} | *{_eur(total_hp_cpl)} CPL*"},
            {"type":"mrkdwn","text":f"*Weekly Budget*\n{_eur(total_hp_spend)} / {_eur(hp_weekly_budget)}\n_{_spend_status(total_hp_spend, hp_weekly_budget)}_"},
        ]},
        {"type":"section","text":{"type":"mrkdwn","text":f"*📣 FB Heat Pump Campaigns*\n{fb_hp_camp_text}"}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*🔍 Google Heat Pump Campaigns*\n{ga_hp_camp_text}"}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*♨️ Hot HP Leads*\n{hot_hp_text}"}},
        {"type":"divider"},

        # ── BUDGET & REVENUE MODEL ──
        {"type":"header","text":{"type":"plain_text","text":"💰 Budget & Revenue Model"}},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":(
                f"*Current Revenue Target*\n"
                f"`€200k/month` (incl. VAT)\n"
                f"`{_eur_int(REVENUE_NET)}/month` net\n"
                f"5% budget allowance: `{_eur_int(MONTHLY_MARKETING_BUDGET)}/month`"
            )},
            {"type":"mrkdwn","text":(
                f"*This Week's Spend*\n"
                f"Boiler: `{_eur(total_boiler_spend)}`\n"
                f"HP: `{_eur(total_hp_spend)}`\n"
                f"Total: `{_eur(combined_spend)}` / `{_eur_int(WEEKLY_MARKETING_BUDGET)}` budget\n"
                f"_{_spend_status(combined_spend, WEEKLY_MARKETING_BUDGET)}_"
            )},
        ]},
        {"type":"section","text":{"type":"mrkdwn","text":(
            f"*📈 Capacity Scaling Model*\n"
            f"_(As surveys increase, raise spend & revenue targets accordingly)_\n\n"
            f"{scaling_text}"
        )}},
        {"type":"divider"},

        # ── COMBINED SUMMARY ──
        {"type":"header","text":{"type":"plain_text","text":f"📊 Combined Summary"}},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Total Leads*\n`{combined_leads}`\n_{_wow(combined_leads, (prev_total or 0) + (ga_prev_leads or 0))}_"},
            {"type":"mrkdwn","text":f"*Blended CPL*\n`{_eur(combined_cpl)}`"},
            {"type":"mrkdwn","text":f"*Total Spend*\n`{_eur(combined_spend)}`"},
            {"type":"mrkdwn","text":f"*5% Budget*\n`{_eur_int(WEEKLY_MARKETING_BUDGET)}`/week"},
        ]},
        {"type":"context","elements":[{"type":"mrkdwn",
            "text":f"{COMPANY_NAME} CEO Dashboard • {datetime.utcnow().strftime('%a %d %b %Y %H:%M')} UTC"}]},
    ]

    # Duplicates
    dupes = data.get("duplicate_contacts", [])
    if dupes:
        names = ", ".join(d["name"] for d in dupes[:5])
        if len(dupes) > 5: names += f" +{len(dupes)-5} more"
        blocks.insert(-1, {"type":"section","text":{"type":"mrkdwn",
            "text":f"⚠️ *{len(dupes)} duplicate leads removed:*\n_{names}_"}})

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
