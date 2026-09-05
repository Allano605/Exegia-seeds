"""
Seed `map_locations` from the Pleiades gazetteer of ancient places.

VERIFIED SOURCE: https://atlantides.org/downloads/pleiades/dumps/
  - pleiades-places-latest.csv.gz -- place metadata
  - pleiades-locations-latest.csv.gz -- coordinates, joined via locations.pid == places.id
License: CC BY 3.0 (Ancient World Mapping Center / ISAW) -- attribution required in-app.

FIXED 2026-09-05, three real bugs found from live runs:
1. Jerusalem (and other places) failed to match because Pleiades titles are
   often COMPOUND strings -- Jerusalem's real title is
   "Ierusalem/Hierosolyma/Col. Aelia Capitolina". Fixed by indexing each
   "/"-separated component, plus a NAME_ALIASES table for known cases.
2. Some Pleiades locations are LineStrings/Polygons, not simple Points, so
   coordinates are nested lists -- fixed via extract_representative_point(),
   which averages all points in any geometry shape into one coordinate.
3. "Ephesus" was accidentally listed twice in BIBLICAL_PLACES, which crashed
   the whole insert batch with a unique-constraint violation. Removed the
   duplicate and added a dedup safety net so this can't happen silently again.

Run: python seed_map_locations.py
"""
import csv
import gzip
import io
import json
import sys
import requests
from tqdm import tqdm
from _client import supabase

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)

PLACES_URL = "https://atlantides.org/downloads/pleiades/dumps/pleiades-places-latest.csv.gz"
LOCATIONS_URL = "https://atlantides.org/downloads/pleiades/dumps/pleiades-locations-latest.csv.gz"

NAME_ALIASES = {
    "Jerusalem": ["Ierusalem"],
}

BIBLICAL_PLACES = [
    "Jerusalem", "Bethlehem", "Nazareth", "Capernaum", "Jericho", "Bethany",
    "Damascus", "Antioch", "Antioch on the Orontes", "Caesarea", "Caesarea Maritima",
    "Tyre", "Sidon", "Joppa", "Samaria", "Hebron", "Bethel", "Shechem", "Babylon",
    "Nineveh", "Ur", "Haran", "Sinai", "Ephesus", "Corinth", "Athens", "Philippi",
    "Thessalonica", "Berea", "Rome", "Cyprus", "Paphos", "Salamis", "Iconium",
    "Lystra", "Derbe", "Perga", "Attalia", "Troas", "Neapolis", "Amphipolis",
    "Apollonia", "Miletus", "Assos", "Mitylene", "Chios", "Samos", "Patara",
    "Cnidus", "Crete", "Fair Havens", "Malta", "Syracuse", "Rhegium", "Puteoli",
    "Appii Forum", "Colossae", "Laodicea", "Smyrna", "Pergamum", "Thyatira",
    "Sardis", "Philadelphia", "Patmos", "Alexandria", "Cyrene",
]


def download_csv_gz(url, description):
    print(f"Downloading {description}...")
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows)} rows")
    return rows


def _flatten_coords(coords):
    if not coords:
        return []
    if len(coords) == 2 and all(isinstance(c, (int, float)) for c in coords):
        return [coords]
    pairs = []
    for item in coords:
        pairs.extend(_flatten_coords(item))
    return pairs


def extract_representative_point(geom):
    if not geom or "coordinates" not in geom:
        return None, None
    pairs = _flatten_coords(geom["coordinates"])
    if not pairs:
        return None, None
    lon = sum(p[0] for p in pairs) / len(pairs)
    lat = sum(p[1] for p in pairs) / len(pairs)
    return lon, lat


def run():
    places = download_csv_gz(PLACES_URL, "Pleiades places")
    locations = download_csv_gz(LOCATIONS_URL, "Pleiades locations")

    places_by_title = {}
    places_by_component = {}
    for p in places:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        title_lower = title.lower()
        if title_lower not in places_by_title:
            places_by_title[title_lower] = p
        for component in title.split("/"):
            comp_lower = component.strip().lower()
            if comp_lower and comp_lower not in places_by_component:
                places_by_component[comp_lower] = p

    def normalize_id(raw_id):
        if not raw_id:
            return None
        return str(raw_id).strip().rstrip("/").split("/")[-1]

    locations_by_pid = {}
    for loc in locations:
        pid = normalize_id(loc.get("pid"))
        if pid and pid not in locations_by_pid:
            locations_by_pid[pid] = loc

    if places:
        print(f"  sample places.id format: {places[0].get('id')!r}")
    if locations:
        print(f"  sample locations.pid format: {locations[0].get('pid')!r}")

    def find_place(name):
        exact = places_by_title.get(name.lower())
        if exact:
            return exact
        for alias in NAME_ALIASES.get(name, []):
            found = places_by_title.get(alias.lower()) or places_by_component.get(alias.lower())
            if found:
                return found
        return places_by_component.get(name.lower())

    rows = []
    unmatched = []
    for name in tqdm(BIBLICAL_PLACES, desc="Matching biblical places"):
        place = find_place(name)
        if not place:
            unmatched.append(name)
            continue
        loc = locations_by_pid.get(normalize_id(place["id"]))
        if not loc or not loc.get("geometry"):
            unmatched.append(f"{name} (place found, no coordinates)")
            continue
        try:
            geom = json.loads(loc["geometry"])
            lon, lat = extract_representative_point(geom)
            if lon is None or lat is None:
                unmatched.append(f"{name} (unsupported geometry type: {geom.get('type')})")
                continue
        except (KeyError, ValueError, TypeError, IndexError):
            unmatched.append(f"{name} (unparseable geometry: {loc.get('geometry')})")
            continue

        rows.append(
            {
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "description": place.get("description") or None,
                "source": "Pleiades (pleiades.stoa.org), CC BY 3.0",
            }
        )

    print(f"\nMatched {len(rows)}/{len(BIBLICAL_PLACES)} places.")
    if unmatched:
        print(f"Unmatched ({len(unmatched)}):")
        for u in unmatched:
            print(f"  - {u}")

    seen_names = set()
    deduped_rows = []
    for r in rows:
        if r["name"] not in seen_names:
            seen_names.add(r["name"])
            deduped_rows.append(r)
    rows = deduped_rows

    if not rows:
        raise RuntimeError("Matched 0 places -- check the sample id/pid formats printed above.")

    existing_resp = supabase.table("map_locations").select("name").execute()
    existing_names = {r["name"] for r in existing_resp.data}
    new_rows = [r for r in rows if r["name"] not in existing_names]
    for i in range(0, len(new_rows), 500):
        supabase.table("map_locations").insert(new_rows[i:i + 500]).execute()
    print(f"Inserted {len(new_rows)} new locations ({len(rows) - len(new_rows)} already existed).")

    print("Map location seeding complete.")


if __name__ == "__main__":
    run()
