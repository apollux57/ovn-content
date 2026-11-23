import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
import requests

UDOT_API_KEY = os.environ.get("UDOT_API_KEY", "").strip()
UDOT_BASE = "https://www.udottraffic.utah.gov/api/v2/get"
SNOTEL_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"
NWS_HEADERS = {
    "User-Agent": "(ogdenvalleynews.com, contact@ogdenvalleynews.com)",
    "Accept": "application/geo+json",
}

# Bounding box covering Ogden Valley, Ogden Canyon, Weber Canyon, and North Ogden Divide
BBOX = {"min_lat": 41.12, "max_lat": 41.45, "min_lon": -112.02, "max_lon": -111.60}

# Target corridors and keywords
CORRIDOR_KEYWORDS = [
    "SR-39", "SR-158", "SR-226", "SR-167", "I-84",
    "OGDEN CANYON", "POWDER MOUNTAIN", "SNOWBASIN",
    "TRAPPERS LOOP", "NORTH OGDEN", "HUNTSVILLE", "EDEN", "WEBER CANYON"
]

RESORTS = {
    "snowbasin": {"name": "Snowbasin", "lat": 41.2160, "lon": -111.8569},
    "powder_mountain": {"name": "Powder Mountain", "lat": 41.3790, "lon": -111.7803},
    "nordic_valley": {"name": "Nordic Valley", "lat": 41.3106, "lon": -111.8648},
    "ogden_nordic": {"name": "Ogden Nordic", "lat": 41.3660, "lon": -111.9110},
}

SNOTEL_STATIONS = {
    "ben_lomond_peak": {
        "triplet": "332:UT:SNTL",
        "name": "Ben Lomond Peak",
        "elevation_ft": 7690,
        "reference_for": "Snowbasin / Nordic Valley",
    },
    "monte_cristo": {
        "triplet": "634:UT:SNTL",
        "name": "Monte Cristo",
        "elevation_ft": 8960,
        "reference_for": "Powder Mountain / Upper Valley",
    },
}

SKI_UTAH_SLUGS = {
    "snowbasin": "snowbasin",
    "powder_mountain": "powder-mountain",
    "nordic_valley": "nordic-valley",
}


def in_valley_bbox(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        return BBOX["min_lat"] <= lat <= BBOX["max_lat"] and BBOX["min_lon"] <= lon <= BBOX["max_lon"]
    except (TypeError, ValueError):
        return False


def matches_corridor(text):
    upper = (text or "").upper()
    return any(kw in upper for kw in CORRIDOR_KEYWORDS)


def fetch_udot(endpoint):
    if not UDOT_API_KEY:
        print(f"Skipping UDOT {endpoint}: UDOT_API_KEY not set.")
        return []
    url = f"{UDOT_BASE}/{endpoint}"
    try:
        resp = requests.get(url, params={"key": UDOT_API_KEY, "format": "json"}, timeout=20)
        resp.raise_for_status()
        time.sleep(1)  # Respect UDOT 10 calls / 60s throttle
        return resp.json()
    except Exception as e:
        print(f"UDOT {endpoint} error: {e}")
        return []


def get_udot_data():
    raw_cams = fetch_udot("cameras")
    cameras = []
    for c in raw_cams:
        loc = f"{c.get('Location', '')} {c.get('Roadway', '')}"
        if in_valley_bbox(c.get("Latitude"), c.get("Longitude")) or matches_corridor(loc):
            views = c.get("Views") or []
            img_url = views[0].get("Url") if views else c.get("Url", "")
            if img_url:
                cameras.append({
                    "id": c.get("Id"),
                    "name": c.get("Location") or c.get("Roadway"),
                    "roadway": c.get("Roadway", ""),
                    "url": img_url,
                    "lat": c.get("Latitude"),
                    "lon": c.get("Longitude"),
                })

    raw_signs = fetch_udot("messagesigns")
    signs = []
    for s in raw_signs:
        loc = f"{s.get('Name', '')} {s.get('Roadway', '')}"
        if in_valley_bbox(s.get("Latitude"), s.get("Longitude")) or matches_corridor(loc):
            messages = s.get("Messages") or []
            if messages:
                signs.append({
                    "name": s.get("Name"),
                    "roadway": s.get("Roadway", ""),
                    "messages": messages,
                })

    raw_rwis = fetch_udot("weatherstations")
    rwis = []
    for w in raw_rwis:
        loc = f"{w.get('StationName', '')} {w.get('Roadway', '')}"
        if in_valley_bbox(w.get("Latitude"), w.get("Longitude")) or matches_corridor(loc):
            rwis.append({
                "station": w.get("StationName"),
                "air_temp": w.get("AirTemperature"),
                "surface_temp": w.get("SurfaceTemp"),
                "surface_status": w.get("SurfaceStatus"),
                "wind_speed": w.get("WindSpeedAvg"),
                "wind_gust": w.get("WindSpeedGust"),
            })

    raw_roads = fetch_udot("roadconditions")
    roads = []
    for r in raw_roads:
        name = r.get("RoadwayName", "")
        if matches_corridor(name):
            roads.append({
                "roadway": name,
                "condition": r.get("RoadCondition"),
                "weather": r.get("WeatherCondition"),
                "restriction": r.get("Restriction"),
            })

    return {"cameras": cameras, "signs": signs, "rwis": rwis, "roads": roads}


def get_nws_resort_weather():
    weather = {}
    for key, info in RESORTS.items():
        try:
            pt_url = f"https://api.weather.gov/points/{info['lat']},{info['lon']}"
            pt_resp = requests.get(pt_url, headers=NWS_HEADERS, timeout=15)
            pt_resp.raise_for_status()
            forecast_url = pt_resp.json()["properties"]["forecast"]

            fc_resp = requests.get(forecast_url, headers=NWS_HEADERS, timeout=15)
            fc_resp.raise_for_status()
            periods = fc_resp.json()["properties"]["periods"][:4]

            weather[key] = {
                "name": info["name"],
                "current_period": periods[0] if periods else None,
                "upcoming": [
                    {
                        "name": p["name"],
                        "temp": p["temperature"],
                        "unit": p["temperatureUnit"],
                        "wind": p["windSpeed"],
                        "short": p["shortForecast"],
                        "detail": p["detailedForecast"],
                    }
                    for p in periods
                ],
            }
        except Exception as e:
            print(f"NWS error for {key}: {e}")
            weather[key] = {"name": info["name"], "error": str(e)}

    alerts = []
    try:
        al_resp = requests.get(
            "https://api.weather.gov/alerts/active",
            params={"point": "41.3005,-111.8124"},
            headers=NWS_HEADERS,
            timeout=15,
        )
        al_resp.raise_for_status()
        for f in al_resp.json().get("features", []):
            props = f.get("properties", {})
            alerts.append({
                "event": props.get("event"),
                "headline": props.get("headline"),
                "severity": props.get("severity"),
                "expires": props.get("expires"),
            })
    except Exception as e:
        print(f"NWS alerts error: {e}")

    return {"resorts": weather, "alerts": alerts}


def get_snotel_data():
    """Fetch hourly (with daily fallback) Snow Depth (SNWD), SWE (WTEQ), and Temp (TOBS)."""
    now_utc = datetime.now(timezone.utc)
    begin_date = (now_utc - timedelta(days=2)).strftime("%Y-%m-%d")
    end_date = now_utc.strftime("%Y-%m-%d")

    triplets = ",".join(s["triplet"] for s in SNOTEL_STATIONS.values())

    def fetch_duration(duration):
        params = {
            "stationTriplets": triplets,
            "elements": "SNWD,WTEQ,TOBS",
            "duration": duration,
            "beginDate": begin_date,
            "endDate": end_date,
        }
        resp = requests.get(SNOTEL_BASE, params=params, timeout=25)
        resp.raise_for_status()
        return resp.json()

    results = {}
    try:
        raw_stations = fetch_duration("HOURLY")
        if not raw_stations:
            raw_stations = fetch_duration("DAILY")

        by_triplet = {item.get("stationTriplet"): item.get("data", []) for item in raw_stations}

        for key, meta in SNOTEL_STATIONS.items():
            series_list = by_triplet.get(meta["triplet"], [])
            parsed = {}
            for s in series_list:
                code = s.get("stationElement", {}).get("elementCode")
                vals = [v for v in s.get("values", []) if v.get("value") is not None]
                parsed[code] = vals

            snwd_vals = parsed.get("SNWD", [])
            wteq_vals = parsed.get("WTEQ", [])
            tobs_vals = parsed.get("TOBS", [])

            latest_depth = snwd_vals[-1]["value"] if snwd_vals else None
            latest_time = snwd_vals[-1]["date"] if snwd_vals else None

            snow_24h = None
            if len(snwd_vals) >= 2:
                idx_24h = max(0, len(snwd_vals) - 25)
                prior_depth = snwd_vals[idx_24h]["value"]
                snow_24h = max(0, round(latest_depth - prior_depth, 1))

            results[key] = {
                "name": meta["name"],
                "triplet": meta["triplet"],
                "elevation_ft": meta["elevation_ft"],
                "reference_for": meta["reference_for"],
                "snow_depth_in": latest_depth,
                "snow_24h_in": snow_24h,
                "swe_in": wteq_vals[-1]["value"] if wteq_vals else None,
                "temp_f": tobs_vals[-1]["value"] if tobs_vals else None,
                "observed_at": latest_time,
            }
    except Exception as e:
        print(f"SNOTEL fetch error: {e}")
        results["error"] = str(e)

    return results


def get_resort_snow_reports():
    """Fetch snow stats, open/closed status, and projected opening dates from Ski Utah."""
    reports = {}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OgdenValleyNewsBot/1.0)"}

    for key, slug in SKI_UTAH_SLUGS.items():
        report_url = f"https://www.skiutah.com/members/{slug}/snowreport"
        info_url = f"https://www.skiutah.com/members/{slug}/"
        try:
            resp = requests.get(report_url, headers=headers, timeout=20)
            resp.raise_for_status()
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp.text))

            def grab(pattern, src=text):
                m = re.search(pattern, src, re.IGNORECASE)
                return m.group(1).strip() if m else None

            lifts = (
                grab(r"(\d+\s*/\s*\d+)\s+lifts\s*open")
                or grab(r"lifts\s*open\s*[:\-]?\s*(\d+\s*/\s*\d+)")
                or grab(r"(\d+\s*of\s*\d+)\s+lifts")
            )

            # Fetch projected opening date from the resort's Ski Utah member info page
            projected_opening = None
            try:
                info_resp = requests.get(info_url, headers=headers, timeout=15)
                if info_resp.ok:
                    info_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", info_resp.text))
                    projected_opening = (
                        grab(r"Winter\s+open\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})", info_text)
                        or grab(r"Anticipated\s+Winter\s+Opening\s+Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", info_text)
                    )
            except Exception:
                pass

            # Determine Open vs. Pre-Season / Closed status
            status = "Closed"
            if lifts:
                first_num = int(re.split(r"[/a-zA-Z]+", lifts)[0].strip())
                status = "Open" if first_num > 0 else "Closed"
            elif re.search(r"\b(resort\s+is\s+open|open\s+daily|now\s+open)\b", text, re.IGNORECASE):
                status = "Open"

            reports[key] = {
                "status": status,
                "projected_opening": projected_opening,
                "snow_24h": grab(r"Past 24 HR\s+(\d+)\s*[\"”']?"),
                "base_depth": grab(r"base depth\s+(\d+)\s*[\"”']?"),
                "season_total": grab(r"year to date\s+(\d+)\s*[\"”']?"),
                "lifts_open": lifts,
                "runs_open": grab(r"(\d+\s*/\s*\d+)\s+runs"),
                "source_url": report_url,
            }
        except Exception as e:
            print(f"Ski Utah report error for {key}: {e}")
            reports[key] = {"status": "Closed", "error": str(e), "source_url": report_url}

    return reports


def fetch_pws_station(station_id):
    """Fetch current observations for a Weather Underground PWS station."""
    api_key = os.environ.get("WU_API_KEY", "").strip()
    if not api_key:
        print(f"Skipping PWS {station_id}: WU_API_KEY not set.")
        return None

    url = (
        "https://api.weather.com/v2/pws/observations/current"
        f"?stationId={station_id}&format=json&units=e&apiKey={api_key}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        obs_list = resp.json().get("observations") or []
        if not obs_list:
            return None
        obs = obs_list[0]
        imp = obs.get("imperial") or {}
        return {
            "station_id": station_id,
            "temp_f": imp.get("temp"),
            "wind_mph": imp.get("windSpeed"),
            "wind_gust_mph": imp.get("windGust"),
            "humidity": obs.get("humidity"),
            "obs_time_local": obs.get("obsTimeLocal"),
        }
    except Exception as e:
        print(f"PWS fetch error ({station_id}): {e}")
        return None


def main():
    pws_kutliber14 = fetch_pws_station("KUTLIBER14")
    pws_data = {"KUTLIBER14": pws_kutliber14} if pws_kutliber14 else {}

    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "udot": get_udot_data(),
        "nws": get_nws_resort_weather(),
        "snotel": get_snotel_data(),
        "snow_reports": get_resort_snow_reports(),
        "pws": pws_data,
    }
    with open("ovn-ski-data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print("Saved ovn-ski-data.json successfully.")


if __name__ == "__main__":
    main()
