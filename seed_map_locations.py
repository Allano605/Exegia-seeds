import csv, gzip, io, json, sys, requests
from tqdm import tqdm
from _client import supabase

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)

PLACES_URL = "https://atlantides.org/downloads/pleiades/dumps/pleiades-places-latest.csv.gz"
LOCATIONS_URL = "https://atlantides.org/downloads/pleiades/dumps/pleiades-locations-latest.csv.gz"

BIBLICAL_PLACES = [
    "Jerusalem", "Bethlehem", "Nazareth", "Capernaum", "Jericho", "Bethany",
    "Damascus", "Antioch", "Caesarea", "Tyre", "Sidon", "Joppa", "Samaria", "Hebron",
    "Bethel", "Shechem", "Babylon", "Nineveh", "Ur", "Haran", "Sinai", "Ephesus",
    "Corinth", "Athens", "Philippi", "Thessalonica", "Berea", "Rome", "Cyprus",
    "Paphos", "Salamis", "Iconium", "Lystra", "Derbe", "Perga", "Attalia", "Troas",
    "Neapolis", "Amphipolis", "Apollonia", "Miletus", "Assos", "Mitylene", "Chios",
    "Samos", "Patara", "Cnidus", "Crete", "Malta", "Syracuse", "Rhegium", "Puteoli"
]

def download_csv_gz(url, desc):
    print(f"Downloading {desc}...")
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f" {len(rows)} rows")
    return rows

def normalize_id(raw_id):
    if not raw_id:
        return None
    return str(raw_id).strip().rstrip("/").split("/")[-1]

def run():
    places = download_csv_gz(PLACES_URL, "Pleiades places")
    locations = download_csv_gz(LOCATIONS_URL, "Pleiades locations")

    places_by_title = {}
    for p in places:
        title = (p.get("title") or "").strip().lower()
        if title and title not in places_by_title:
            places_by_title[title] = p

    locations_by_pid = {}
    for loc in locations:
        pid = normalize_id(loc.get("pid"))
        if pid and pid not in locations_by_pid:
            locations_by_pid[pid] = loc

    rows = []
    unmatched = []
    for name in tqdm(BIBLICAL_PLACES, desc="Matching"):
        place = places_by_title.get(name.lower())
        if not place:
            unmatched.append(name)
            continue
        loc = locations_by_pid.get(normalize_id(place["id"]))
        if not loc or not loc.get("geometry"):
            unmatched.append(f"{name} (no coords)")
            continue
        try:
            geom = json.loads(loc["geometry"])
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            if not coords:
                raise ValueError("empty")

            if gtype == "Point":
                lon, lat = coords[0], coords[1]
            elif gtype == "Polygon":
                ring = coords[0]
                lon = sum(c[0] for c in ring) / len(ring)
                lat = sum(c[1] for c in ring) / len(ring)
            elif gtype == "MultiPolygon":
                ring = coords[0][0]
                lon = sum(c[0] for c in ring) / len(ring)
                lat = sum(c[1] for c in ring) / len(ring)
            else:
                first = coords[0]
                if isinstance(first[0], (list, tuple)):
                    lon, lat = first[0][0], first[0][1]
                else:
                    lon, lat = first[0], first[1]
        except Exception as e:
            unmatched.append(f"{name} ({e})")
            continue

        rows.append({
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "description": place.get("description") or None,
            "source": "Pleiades, CC BY 3.0"
        })

    print(f"Matched {len(rows)}/{len(BIBLICAL_PLACES)}")
    if unmatched:
        for u in unmatched:
            print(f" - {u}")

    if not rows:
        raise RuntimeError("Matched 0 places")

    existing = supabase.table("map_locations").select("name").execute()
    existing_names = {r["name"] for r in existing.data}
    new_rows = [r for r in rows if r["name"] not in existing_names]

    for i in range(0, len(new_rows), 500):
        supabase.table("map_locations").insert(new_rows[i:i+500]).execute()

    print(f"Inserted {len(new_rows)} new")

if __name__ == "__main__":
    run()
