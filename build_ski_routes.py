import json
import os
import time
import requests

DATA_URL = "https://raw.githubusercontent.com/apollux57/ovn-content/main/ovn-ski-data.json"
OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"
OUTPUT_FILE = "ovn-ski-routes.json"

ROUTES = [
    {
        "id": "sb-i84-wb",
        "label": "Snowbasin: From I-84 WB",
        "cams": ["177630", "178584", "178027", "179250"],
        "destination": {"name": "Snowbasin Resort", "lat": 41.2160, "lon": -111.8569},
    },
    {
        "id": "sb-i15-i84",
        "label": "Snowbasin: I-15 NB to I-84 EB",
        "cams": ["179778", "177560", "180009", "178367", "179622", "178027", "179250"],
        "destination": {"name": "Snowbasin Resort", "lat": 41.2160, "lon": -111.8569},
    },
    {
        "id": "sb-12th",
        "label": "Snowbasin: I-15 to 12th St EB",
        "cams": ["178202", "179479", "178954", "178920", "178027", "179250"],
        "destination": {"name": "Snowbasin Resort", "lat": 41.2160, "lon": -111.8569},
    },
    {
        "id": "pm-12th",
        "label": "Powder Mtn: I-15 to 12th St EB",
        "cams": ["178202", "179479", "178954", "179759", "179677"],
        "destination": {"name": "Powder Mountain", "lat": 41.3790, "lon": -111.7803},
    },
    {
        "id": "pm-2700n",
        "label": "Powder Mtn: I-15 to 2700 N / Divide",
        "cams": ["177583", "179879", "179625", "178351", "179759", "179677"],
        "destination": {"name": "Powder Mountain", "lat": 41.3790, "lon": -111.7803},
    },
    {
        "id": "nv-12th",
        "label": "Nordic Valley: I-15 to 12th St EB",
        "cams": ["178202", "179479", "178954"],
        "destination": {"name": "Nordic Valley", "lat": 41.3106, "lon": -111.8648},
    },
    {
        "id": "nv-2700n",
        "label": "Nordic Valley: I-15 to 2700 N / Divide",
        "cams": ["177583", "179879", "179625", "178351"],
        "destination": {"name": "Nordic Valley", "lat": 41.3106, "lon": -111.8648},
    },
    {
        "id": "on-12th",
        "label": "Ogden Nordic: I-15 to 12th St EB",
        "cams": ["178202", "179479", "178954"],
        "destination": {"name": "Ogden Nordic", "lat": 41.3660, "lon": -111.9110},
    },
    {
        "id": "on-2700n",
        "label": "Ogden Nordic: I-15 to 2700 N / Divide",
        "cams": ["177583", "179879", "179625", "178351"],
        "destination": {"name": "Ogden Nordic", "lat": 41.3660, "lon": -111.9110},
    },
]


def load_camera_coords():
    """Load camera coordinates from local ovn-ski-data.json if present, otherwise from GitHub."""
    if os.path.exists("ovn-ski-data.json"):
        with open("ovn-ski-data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        resp = requests.get(DATA_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()

    by_id = {}
    for cam in (data.get("udot") or {}).get("cameras", []):
        cid = cam.get("cctv_id")
        if cid and cam.get("lat") is not None and cam.get("lon") is not None:
            by_id[str(cid)] = (float(cam["lat"]), float(cam["lon"]))
    return by_id


def fetch_osrm_geometry(waypoints):
    """Fetch GeoJSON LineString from OSRM for a list of (lat, lon) tuples."""
    if len(waypoints) < 2:
        return None
    # OSRM expects lon,lat order
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
    url = f"{OSRM_BASE}/{coords}"
    params = {"overview": "full", "geometries": "geojson"}
    resp = requests.get(url, params=params, timeout=25)
    resp.raise_for_status()
    payload = resp.json()
    routes = payload.get("routes") or []
    if not routes:
        return None
    return routes[0].get("geometry")


def main():
    cam_coords = load_camera_coords()
    print(f"Loaded {len(cam_coords)} camera coordinates.")

    output = {"routes": {}}

    for r in ROUTES:
        rid = r["id"]
        dest = r["destination"]
        cam_pts = []
        missing = []

        for cid in r["cams"]:
            if cid in cam_coords:
                cam_pts.append(cam_coords[cid])
            else:
                missing.append(cid)

        if missing:
            print(f"WARNING [{rid}]: Missing coordinates for cameras: {missing}")

        print(f"Fetching OSRM road geometry for {rid} ({r['label']})...")
        cam_geom = fetch_osrm_geometry(cam_pts)
        time.sleep(1.2)  # Be polite to the public OSRM server

        dest_geom = None
        if cam_pts:
            dest_geom = fetch_osrm_geometry([cam_pts[-1], (dest["lat"], dest["lon"])])
            time.sleep(1.2)

        output["routes"][rid] = {
            "id": rid,
            "label": r["label"],
            "cams": r["cams"],
            "destination": dest,
            "cam_geometry": cam_geom,
            "dest_geometry": dest_geom,
        }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Saved all 9 pre-baked routes to {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()