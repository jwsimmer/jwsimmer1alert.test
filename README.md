# Early Warning Pipeline: Setup

## 1. Phone (2 min)
1. Install the **ntfy** app (iOS/Android).
2. Subscribe to a long, random topic name, e.g. `ew-k29xq7v3m1pz`. Anyone who knows it can read your alerts, so treat it like a password.
3. In your phone settings, allow ntfy to bypass Do Not Disturb for urgent (priority 5) alerts.

## 2. Test locally (dry run, no topic set)
    python3 alert_pipeline.py
It prints what it would send. Then with your topic:
    NTFY_TOPIC=ew-yourtopic CONTACT=you@email.com python3 alert_pipeline.py
The first run only sets a baseline and sends a "system online" message.

## 3. Run it automatically (free)
**Option A: GitHub Actions**
1. Create a **public** repo (public repos get unlimited free minutes; private ones would exceed the free tier at a 10-minute schedule) and upload these files.
2. Settings > Secrets and variables > Actions: add `NTFY_TOPIC` and `CONTACT`.
3. Actions tab > early-warning > Run workflow. Schedules can lag several minutes.

**Option B: Any always-on machine or Raspberry Pi**
    */10 * * * * cd /path/to/early-warning && NTFY_TOPIC=ew-yourtopic CONTACT=you@email.com python3 alert_pipeline.py

## 4. Tuning (top of alert_pipeline.py)
- `HOME_STATES` env var: NWS states covered
- `CENTRAL_AL_COUNTIES`: counties treated as "home turf" for Alabama — check against your
  county and add/remove as needed; this list drives the priority bump below
- `GLOBAL_QUAKE_MIN` / `LOCAL_QUAKE_MIN`: earthquake thresholds
- `CONFLICT_RE`: headline keywords for conflict escalation
- `NEWS_FEEDS`: add or remove RSS sources

## Priority map
5 = Extreme weather anywhere, or any Severe/Extreme NWS warning for a Central Alabama county
    (tornado, severe thunderstorm/hail, flash flood, high wind, winter storm, etc.),
    Red disasters, local quakes (all breaks Do Not Disturb)
4 = Severe weather elsewhere in your home states, Orange disasters, hurricane advisories,
    Level 4 travel advisories, high-risk food recalls (Class I/E. coli/Listeria/botulism),
    CDC Health Alert Network notices
3 = Moderate-severity NWS advisories for Central Alabama (heat, cold, wind, flood advisories
    that NWS doesn't rate "Severe"), conflict headlines, routine food/product recalls (quiet)

## Sources (9 total)
NWS (weather) · USGS (earthquakes) · GDACS (global disasters) · NHC (hurricanes) ·
State Dept (travel advisories) · BBC/Al Jazeera (conflict headlines) ·
FDA (food recalls) · USDA FSIS (meat/poultry recalls) · CPSC (consumer product recalls) ·
CDC Health Alert Network (disease outbreaks, public health emergencies)
