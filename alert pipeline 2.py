#!/usr/bin/env python3
"""Personal early-warning pipeline. Pulls free public feeds, filters them,
and pushes alerts to your phone through ntfy.sh. Standard library only.

Env vars:
  NTFY_TOPIC    your secret ntfy topic (if unset, alerts print instead: dry run)
  CONTACT       your email (NWS asks API users to identify themselves)
  HOME_STATES   comma list, default "AL,FL,GA,MS,NC,SC,TN,VA"
  STATE_FILE    default "state.json"
"""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
CONTACT = os.environ.get("CONTACT", "you@example.com")
STATES = [s.strip() for s in os.environ.get("HOME_STATES", "AL,FL,GA,MS,NC,SC,TN,VA").split(",")]
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
UA = f"personal-early-warning/1.0 ({CONTACT})"
MAX_PER_RUN = 10

# Southeast US bounding box for local earthquakes
SE_BOX = {"lat": (24.0, 39.5), "lon": (-92.0, -75.0)}

# Counties NWS groups under "Central Alabama" (Birmingham/Montgomery forecast areas).
# Matched against each alert's areaDesc text. Edit this list if your county is missing.
CENTRAL_AL_COUNTIES = [
    "Jefferson", "Shelby", "Tuscaloosa", "Bibb", "Chilton", "Autauga", "Elmore",
    "Montgomery", "Blount", "St. Clair", "Talladega", "Coosa", "Walker", "Perry",
    "Hale", "Dallas", "Lowndes", "Pickens", "Greene", "Lamar", "Fayette", "Marengo",
    "Lee", "Macon", "Chambers", "Tallapoosa", "Randolph", "Clay", "Pike", "Bullock",
]
GLOBAL_QUAKE_MIN = 6.0
LOCAL_QUAKE_MIN = 2.5

# Conflict-escalation keywords (headline match only; tune to taste)
CONFLICT_RE = re.compile(
    r"\b(declares? war|invasion|invades?|missile (strike|attack|launch)|airstrikes?|"
    r"nuclear (test|threat|alert|plant attack)|martial law|general mobili[sz]ation|"
    r"ceasefire (collapses|ends|breaks)|drone attack|state of emergency|coup)\b",
    re.I,
)
NEWS_FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}
TRAVEL_FEED = "https://travel.state.gov/_res/rss/TAsTWs.xml"
NHC_FEED = "https://www.nhc.noaa.gov/index-at.xml"
GDACS_FEED = "https://www.gdacs.org/xml/rss.xml"
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
FDA_RECALL_FEED = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/food-safety/rss.xml"
FSIS_RECALL_API = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
CPSC_RECALL_FEED = "https://www.cpsc.gov/Newsroom/RSS-Feeds/recalls-feed.xml"
CDC_HAN_FEED = "https://tools.cdc.gov/api/v2/resources/media/404952.rss"  # Health Alert Network


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def fetch_json(url):
    return json.loads(fetch(url))


def fetch_rss(url):
    root = ET.fromstring(fetch(url))
    return root.findall(".//item")


def text(item, tag):
    el = item.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


# ---------- sources: each returns list of (id, title, body, priority, tags, link) ----------

def nws():
    out = []
    data = fetch_json(f"https://api.weather.gov/alerts/active?area={','.join(STATES)}&status=actual")
    for f in data.get("features", []):
        p = f["properties"]
        sev = p.get("severity")
        area = p.get("areaDesc", "")
        event = p.get("event", "")
        is_central_al = any(c in area for c in CENTRAL_AL_COUNTIES)

        if sev in ("Extreme", "Severe"):
            # Central AL gets bumped a notch above the same alert elsewhere, since it's home turf
            prio = 5 if (sev == "Extreme" or is_central_al) else 4
        elif sev == "Moderate" and is_central_al:
            # Catches heat/cold advisories, wind advisories, flood advisories etc. that NWS
            # rates below "Severe" but that still matter locally (tornado/t-storm/flood/hail
            # warnings are already "Severe" or "Extreme" and covered by the branch above)
            prio = 3
        else:
            continue

        body = f"{area}\n{p.get('headline', '')}\n{(p.get('instruction') or '')[:300]}"
        tags = "tornado" if "Tornado" in event else "cloud_with_lightning"
        out.append((p["id"], f"NWS: {event}", body, prio, tags, None))
    return out


def usgs():
    out = []
    for f in fetch_json(USGS_FEED).get("features", []):
        p, (lon, lat, _) = f["properties"], f["geometry"]["coordinates"]
        mag = p.get("mag") or 0
        local = (SE_BOX["lat"][0] <= lat <= SE_BOX["lat"][1]
                 and SE_BOX["lon"][0] <= lon <= SE_BOX["lon"][1])
        if mag >= GLOBAL_QUAKE_MIN or (local and mag >= LOCAL_QUAKE_MIN):
            tsu = " | Tsunami flag set" if p.get("tsunami") else ""
            prio = 5 if local or mag >= 7 else 4
            out.append((f["id"], f"Quake M{mag:.1f}", f"{p.get('place')}{tsu}", prio,
                        "earth_americas", p.get("url")))
    return out


def gdacs():
    out = []
    ns = {"g": "http://www.gdacs.org"}
    for it in fetch_rss(GDACS_FEED):
        level = (it.findtext("g:alertlevel", default="", namespaces=ns) or "").strip()
        if level not in ("Orange", "Red"):
            continue
        kind = it.findtext("g:eventtype", default="", namespaces=ns)
        guid = text(it, "guid") or text(it, "link")
        out.append((f"gdacs:{guid}:{level}", f"GDACS {level}: {kind}", text(it, "title"),
                    5 if level == "Red" else 4, "warning", text(it, "link")))
    return out


def nhc():
    out = []
    for it in fetch_rss(NHC_FEED):
        title = text(it, "title")
        if re.search(r"(Hurricane|Tropical Storm|Tropical Depression|Potential Tropical Cyclone)", title) \
                and "Advisory" in title:
            out.append((f"nhc:{text(it, 'guid') or title}", "NHC Atlantic", title, 4,
                        "cyclone", text(it, "link")))
    return out


def travel():
    out = []
    for it in fetch_rss(TRAVEL_FEED):
        title = text(it, "title")
        if "Level 4" in title:
            out.append((f"ta:{text(it, 'guid') or title}", "Travel: Do Not Travel", title, 4,
                        "passport_control", text(it, "link")))
    return out


def conflict_news():
    out = []
    for name, url in NEWS_FEEDS.items():
        for it in fetch_rss(url):
            title = text(it, "title")
            if CONFLICT_RE.search(title):
                out.append((f"news:{text(it, 'link') or title}", f"{name} headline", title, 3,
                            "crossed_swords", text(it, "link")))
    return out


def food_recalls():
    out = []
    # FDA food safety recalls (RSS)
    for it in fetch_rss(FDA_RECALL_FEED):
        title = text(it, "title")
        guid = text(it, "guid") or text(it, "link") or title
        urgent = bool(re.search(r"\b(Class I|death|E\. ?coli|botulism|Listeria)\b", title, re.I))
        out.append((f"fda:{guid}", "FDA Food Recall", title, 4 if urgent else 3,
                    "stethoscope", text(it, "link")))
    # USDA FSIS meat/poultry recalls (JSON API)
    try:
        data = fetch_json(FSIS_RECALL_API)
        for r in data[:25]:
            rid = str(r.get("field_recall_number") or r.get("field_recall_url") or r.get("field_title"))
            title = r.get("field_title", "FSIS recall")
            urgent = str(r.get("field_risk_level", "")).lower().startswith("high")
            out.append((f"fsis:{rid}", "USDA Meat/Poultry Recall", title, 4 if urgent else 3,
                        "stethoscope", r.get("field_recall_url")))
    except Exception as e:
        print(f"[warn] fsis failed: {e}", file=sys.stderr)
    # Consumer product recalls (fire, choking, injury hazards)
    for it in fetch_rss(CPSC_RECALL_FEED):
        title = text(it, "title")
        guid = text(it, "guid") or text(it, "link") or title
        out.append((f"cpsc:{guid}", "CPSC Product Recall", title, 3, "warning", text(it, "link")))
    return out


def health_alerts():
    out = []
    try:
        for it in fetch_rss(CDC_HAN_FEED):
            title = text(it, "title")
            guid = text(it, "guid") or text(it, "link") or title
            out.append((f"cdc:{guid}", "CDC Health Alert", title, 4, "microbe", text(it, "link")))
    except Exception as e:
        print(f"[warn] cdc han failed: {e}", file=sys.stderr)
    return out


SOURCES = [nws, usgs, gdacs, nhc, travel, conflict_news, food_recalls, health_alerts]


# ---------- delivery & state ----------

def notify(title, message, priority=3, tags="", link=None):
    if not NTFY_TOPIC:
        print(f"[DRY RUN p{priority}] {title}: {message[:200]}")
        return
    headers = {
        "Title": title.encode("ascii", "ignore").decode(),
        "Priority": str(priority),
        "Tags": tags,
        "User-Agent": UA,
    }
    if link:
        headers["Click"] = link
    req = urllib.request.Request(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message[:1000].encode(),
                                 headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=20).close()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save_state(seen):
    STATE_FILE.write_text(json.dumps(seen[-3000:]))


def main():
    prior = load_state()
    first_run = prior is None
    seen = prior or []
    seen_set = set(seen)
    new_alerts = []

    for src in SOURCES:
        try:
            for alert in src():
                if alert[0] not in seen_set:
                    seen_set.add(alert[0])
                    seen.append(alert[0])
                    new_alerts.append(alert)
        except Exception as e:  # one broken feed must not kill the rest
            print(f"[warn] {src.__name__} failed: {e}", file=sys.stderr)

    if first_run:
        notify("Early warning online", f"Baseline set ({len(new_alerts)} existing items skipped). "
               "You will be alerted to new items from now on.", 2, "white_check_mark")
    else:
        new_alerts.sort(key=lambda a: -a[3])
        for _id, title, body, prio, tags, link in new_alerts[:MAX_PER_RUN]:
            notify(title, body, prio, tags, link)
        extra = len(new_alerts) - MAX_PER_RUN
        if extra > 0:
            notify("More alerts", f"{extra} additional lower-priority alerts suppressed.", 2)

    save_state(seen)
    print(f"Done. {len(new_alerts)} new item(s).")


if __name__ == "__main__":
    main()
