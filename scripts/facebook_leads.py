import os, math, json, requests
from datetime import datetime, timedelta
from collections import Counter
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_AD_ACCOUNT_ID = "act_481287164585632"
BASE_URL = "https://graph.facebook.com/v19.0"
DUBLIN_LAT, DUBLIN_LNG = 53.3498, -6.2603
HIRING_KEYWORDS = ["hiring", "recruit", "job", "career", "vacancy", "staff"]

EIRCODE_COORDS = {
    "D01":(53.3461,-6.2611),"D02":(53.3394,-6.2602),"D03":(53.3636,-6.2333),
    "D04":(53.3242,-6.2207),"D05":(53.3744,-6.2097),"D06":(53.3198,-6.2678),
    "D6W":(53.3198,-6.2900),"D07":(53.3579,-6.3083),"D08":(53.3354,-6.2872),
    "D09":(53.3836,-6.2394),"D10":(53.3486,-6.3592),"D11":(53.3956,-6.2839),
    "D12":(53.3243,-6.3167),"D13":(53.3900,-6.1833),"D14":(53.2989,-6.2556),
    "D15":(53.3922,-6.3667),"D16":(53.2894,-6.2917),"D17":(53.3697,-6.1956),
    "D18":(53.2697,-6.2036),"D20":(53.3417,-6.4022),"D22":(53.3311,-6.3989),
    "D24":(53.2944,-6.3689),"A82":(53.2731,-6.1339),"A86":(53.2358,-6.1003),
    "A94":(53.2908,-6.1356),"A96":(53.2706,-6.1411),"A98":(53.2022,-6.0978),
    "K36":(53.5000,-6.4167),"K67":(53.4147,-6.7406),"K78":(53.4783,-6.9167),
    "W23":(53.5244,-7.3461),"W91":(53.4239,-8.2653),"F42":(52.3369,-6.4633),
    "F56":(53.7300,-8.0000),"F93":(52.1667,-6.5833),"R14":(52.6592,-7.2525),
    "R51":(52.8631,-7.3008),"R93":(52.5092,-7.8119),"R95":(52.3500,-8.0000),
    "Y25":(52.2583,-7.1119),
}

def is_hiring(name):
    n = (name or "").lower()
    return any(k in n for k in HIRING_KEYWORDS)

def haversine(lat1,lon1,lat2,lon2):
    R=6371
    dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return round(R*2*math.asin(math.sqrt(a)),1)

def get_key(raw):
    if not raw: return None
    c=str(raw).strip().upper().replace(" ","")
    if "DUBLIN" in c or "DUBLN" in c:
        import re; m=re.search(r"\d+",c)
        return f"D{m.group()}" if m else "D01"
    if c in ("MAYO","WICKLOW","ASHBOURNE"): return c
    if c.startswith("D"):
        rest="".join(x for x in c[1:] if x.isdigit())
        if rest: return f"D{rest[:2]}"
    return c[:3] if len(c)>=3 else c

def classify(eircode):
    coords=EIRCODE_COORDS.get(get_key(eircode))
    if not coords: return None,"unknown"
    d=haversine(DUBLIN_LAT,DUBLIN_LNG,coords[0],coords[1])
    return d,("within_10km" if d<=10 else "10_20km" if d<=20 else "outside_20km")

def fetch_forms():
    r=requests.get(f"{BASE_URL}/{FB_PAGE_ID}/leadgen_forms",
        params={"access_token":FB_PAGE_TOKEN,"fields":"id,name","limit":100})
    r.raise_for_status(); return r.json().get("data",[])

def fetch_leads(form_id, since, until):
    url=f"{BASE_URL}/{form_id}/leads"
    params={"access_token":FB_PAGE_TOKEN,
        "fields":"id,created_time,ad_name,adset_name,campaign_name,platform,field_data",
        "filtering":json.dumps([
            {"field":"time_created","operator":"GREATER_THAN","value":int(since.timestamp())},
            {"field":"time_created","operator":"LESS_THAN","value":int(until.timestamp())}]),
        "limit":100}
    leads=[]
    while True:
        r=requests.get(url,params=params); r.raise_for_status(); d=r.json()
        leads.extend(d.get("data",[]));
        nxt=d.get("paging",{}).get("next")
        if not nxt: break
        url=nxt; params={"access_token":FB_PAGE_TOKEN}
    return leads

def fetch_spend(since, until):
    resp = requests.get(f"{BASE_URL}/{FB_AD_ACCOUNT_ID}/insights",
        params={
            "access_token": FB_PAGE_TOKEN,
            "fields": "campaign_name,spend,actions",
            "time_range": json.dumps({"since": since.strftime("%Y-%m-%d"), "until": until.strftime("%Y-%m-%d")}),
            "level": "campaign",
            "limit": 50,
        })
    if resp.status_code != 200:
        print(f"  ⚠️  Could not fetch spend: {resp.json().get('error',{}).get('message','')}")
        return {}
    spend_by_campaign = {}
    for row in resp.json().get("data", []):
        name = row["campaign_name"]
        spend = float(row.get("spend", 0))
        leads = next((int(a["value"]) for a in row.get("actions", []) if a["action_type"] == "lead"), 0)
        spend_by_campaign[name] = {"spend": spend, "leads_api": leads}
    return spend_by_campaign

def parse_fields(field_data):
    result={}
    for item in (field_data or []):
        k=item.get("name","").lower().replace(" ","_")
        v=item.get("values",[])
        result[k]=v[0] if v else None
    return result

def fetch_and_analyse(since=None, until=None, days_back=7):
    if since is None or until is None:
        until=datetime.utcnow(); since=until-timedelta(days=days_back)
    print(f"Fetching Facebook leads {since.date()} → {until.date()}...")
    forms=fetch_forms(); print(f"Found {len(forms)} forms")
    print("Fetching ad spend...")
    spend_data = fetch_spend(since, until)
    raw=[]
    for f in forms:
        leads=fetch_leads(f["id"],since,until)
        if leads: print(f"  {f['name']}: {len(leads)} leads")
        raw.extend(leads)
    print(f"Total leads fetched: {len(raw)}")
    parsed=[]; hiring_leads=[]
    for lead in raw:
        fields=parse_fields(lead.get("field_data",[]))
        eircode=(fields.get("what_is_your_eircode(dublin_only)?") or
                 fields.get("eircode") or fields.get("postcode") or "")
        dist,zone=classify(eircode)
        campaign = lead.get("campaign_name","Unknown") or "Unknown"
        entry = {"id":lead.get("id"),"created_time":lead.get("created_time"),
            "campaign_name":campaign,"platform":lead.get("platform","unknown"),
            "full_name":fields.get("full_name",""),"email":fields.get("email",""),
            "phone":fields.get("phone_number",""),"eircode":eircode,
            "timeline":fields.get("when_are_you_looking_to_replace_your_boiler?","unknown"),
            "reason":fields.get("what_is_your_reason_for_wanting_to_replace?","unknown"),
            "distance_km":dist,"zone":zone}
        if is_hiring(campaign): hiring_leads.append(entry)
        else: parsed.append(entry)
    seen={}; unique=[]; dupes=[]
    for lead in parsed:
        e=(lead["email"] or "").lower().strip()
        if e and e in seen: dupes.append(lead)
        else:
            if e: seen[e]=True
            unique.append(lead)
    total=len(unique)
    zones=Counter(l["zone"] for l in unique)
    campaigns=Counter(l["campaign_name"] for l in unique)
    platforms=Counter(l["platform"] for l in unique)
    timelines=Counter(l["timeline"] for l in unique)
    daily=Counter()
    for l in unique:
        try: daily[l["created_time"][:10]]+=1
        except: pass
    priority=[l for l in unique if l["timeline"] in ("asap","within_1_month") and l["zone"]=="within_10km"]
    cpl_by_campaign = {}
    total_spend = 0.0; hiring_spend = 0.0
    for camp_name, camp_data in spend_data.items():
        spend = camp_data["spend"]
        if is_hiring(camp_name):
            hiring_spend += spend; continue
        total_spend += spend
        form_leads = campaigns.get(camp_name, 0)
        if not form_leads:
            for k, v in campaigns.items():
                if any(word in camp_name for word in k.split()[:3]):
                    form_leads = v; break
        cpl_by_campaign[camp_name] = {"spend":round(spend,2),"leads":form_leads,
            "cpl":round(spend/form_leads,2) if form_leads else None}
    overall_cpl = round(total_spend/total,2) if total else None
    hiring_camp_spend = {}
    for camp_name, camp_data in spend_data.items():
        if is_hiring(camp_name):
            hiring_camp_spend[camp_name] = {"spend":round(camp_data["spend"],2),
                "leads":len([l for l in hiring_leads if l["campaign_name"]==camp_name])}
    return {
        "period":{"from":since.date().isoformat(),"to":until.date().isoformat(),"days":days_back},
        "totals":{"raw":len(parsed),"unique":total,"duplicates":len(dupes)},
        "geography":{"within_10km":zones.get("within_10km",0),"band_10_20km":zones.get("10_20km",0),
            "outside_20km":zones.get("outside_20km",0),"unknown":zones.get("unknown",0),
            "dublin_pct":round((zones.get("within_10km",0)+zones.get("10_20km",0))/total*100) if total else 0},
        "campaigns":dict(campaigns.most_common()),
        "cpl":{"overall":overall_cpl,"total_spend":round(total_spend,2),"by_campaign":cpl_by_campaign},
        "hiring":{"leads":len(hiring_leads),"spend":round(hiring_spend,2),"campaigns":hiring_camp_spend},
        "platforms":dict(platforms),
        "timelines":dict(timelines.most_common()),
        "daily_volume":dict(sorted(daily.items())),
        "priority_leads":len(priority),
        "duplicate_contacts":[{"name":d["full_name"],"email":d["email"]} for d in dupes],
        "_leads":unique,
        "generated_at":datetime.utcnow().isoformat(),
    }

if __name__=="__main__":
    result=fetch_and_analyse()
    print(json.dumps({k:v for k,v in result.items() if k!="_leads"},indent=2))
