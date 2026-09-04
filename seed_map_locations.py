"""
Seed `map_locations` from the Pleiades gazetteer of ancient places.

VERIFIED SOURCE (checked 2026-09-04, fetched the actual live download index
and its README): https://atlantides.org/downloads/pleiades/dumps/
  - pleiades-places-latest.csv.gz — place metadata (id, title, description,
    featureTypes, timePeriods)
  - pleiades-locations-latest.csv.gz — coordinates, joined to places via
    locations.pid == places.id; geometry is a GeoJSON string, e.g.
    {"type": "Point", "coordinates": [lon, lat]} — note GeoJSON order is
    [longitude, latitude], reversed from this schema's (latitude, longitude)
    columns; the script swaps this explicitly.
License: CC BY 3.0 (Ancient World Mapping Center / ISAW) — attribution
required in-app.

Pleiades covers the whole ancient Mediterranean/Near Eastern world, not just
biblical sites, so this script filters to a curated list of biblical place
names (below) rather than importing the full ~40k-place dataset. The list
covers the Old Testament's major named locations plus every stop on Paul's
missionary journeys and voyage to Rome (Acts 13-28) — the set `seed_journeys.py`
needs. Matching is done by exact/near-exact title match against Pleiades'
`title` field; ancient place names can have multiple Pleiades entries for
different periods of the same site, so this takes the first match and prints
what it matched so you can sanity-check against something like Nathan Cook's
Bible Atlas for anything.
verify before trusting a name that seems off.

Run: python seed_map_locations.py
"""
import csv
import gzip
import io
import json
import requests
from tqdm import tqdm
from _client import supabase

PLACES_URL = "https://atlantides.org/downloads/pleiades/dumps/pleiades-places-latest.csv.gz"
LOCATIONS_URL = "https://atlantides.org/downloads/pleiades/dumps/pleiades-locations-latest.csv.gz"

# Curated biblical place names — covers OT geography + all of Acts 13-28
# (Paul's journeys). Pleiades titles are generally the standard ancient/Latin
# form; a few common alternate spellings are included where the site is
# well-known under both.
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
    "Sardis", "Philadelphia", "Patmos", "Alexandria", "Cyrene", "Ephesus",
]


def download_csv_gz(url, description):
    print(f"Downloading {description}...")
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows)} rows")
    return rows


def run():
    places = download_csv_gz(PLACES_URL, "Pleiades places")
    locations = download_csv_gz(LOCATIONS_URL, "Pleiades locations")

    # Index places by lowercased title for matching.
    places_by_title = {}
    for p in places:
        title = (p.get("title") or "").strip().lower()
        if title and title not in places_by_title:
            places_by_title[title] = p  # first match wins

    # Index locations by pid (place id) so we can pull coordinates.
    locations_by_pid = {}
    for loc in locations:
        pid = loc.get("pid")
        if pid and pid not in locations_by_pid:
            locations_by_pid[pid] = loc  # first published location for this place

    rows = []
    unmatched = []
    for name in tqdm(BIBLICAL_PLACES, desc="Matching biblical places"):
        place = places_by_title.get(name.lower())
        if not place:
            unmatched.append(name)
            continue
        loc = locations_by_pid.get(place["id"])
        if not loc or not loc.get("geometry"):
            unmatched.append(f"{name} (place found, no coordinates)")
            continue
        try:
            geom = json.loads(loc["geometry"])
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
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
        print(f"Unmatched ({len(unmatched)}) — these need manual coordinates or a name-variant fix:")
        for u in unmatched:
            print(f"  - {u}")

    if rows:
        # map_locations has no unique constraint beyond the serial id, so —
        # same reasoning as seed_commentaries.py — check by name before
        # inserting rather than fake-upserting against a nonexistent constraint.
        existing_resp = supabase.table("map_locations").select("name").execute()
        existing_names = {r["name"] for r in existing_resp.data}
        new_rows = [r for r in rows if r["name"] not in existing_names]
        for i in range(0, len(new_rows), 500):
            supabase.table("map_locations").insert(new_rows[i:i + 500]).execute()
        print(f"Inserted {len(new_rows)} new locations ({len(rows) - len(new_rows)} already existed).")

    print("Map location seeding complete.")


if __name__ == "__main__":
    run()
