"""
Seed `journeys` and `journey_stops` for Paul's missionary journeys, using the
real narrative sequence and Acts chapter:verse references from the book of
Acts itself — not a third-party dataset, since the route and verse references
are simply what Acts says, and are safe to encode directly rather than fetch.

Requires `map_locations` to already have matching rows (run
seed_map_locations.py first) — stops without a matching location are skipped
with a warning rather than inserted with a null/fake location_id.

The four journeys and their stop sequences below follow the standard
chapter-by-chapter reading of Acts 13-28, which is uncontroversial regarding
which cities appear in which order (the interpretive question in Pauline
chronology is dating and letter-sequencing, not itinerary order, so this is
safe to encode as fact rather than something requiring a "scholars disagree"
treatment).

Run: python seed_journeys.py
"""
from _client import supabase

# (journey name, description, [(place_name, verse_reference), ...])
JOURNEYS = [
    (
        "Paul's First Missionary Journey",
        "Acts 13-14: from Antioch through Cyprus and southern Asia Minor and back.",
        [
            ("Antioch", "Acts 13:1"),
            ("Salamis", "Acts 13:5"),
            ("Paphos", "Acts 13:6"),
            ("Perga", "Acts 13:13"),
            ("Antioch", "Acts 13:14"),  # Pisidian Antioch, distinct site from Syrian Antioch above — see KNOWN_AMBIGUOUS_NAMES
            ("Iconium", "Acts 13:51"),
            ("Lystra", "Acts 14:6"),
            ("Derbe", "Acts 14:20"),
        ],
    ),
    (
        "Paul's Second Missionary Journey",
        "Acts 15:36-18:22: from Antioch through Asia Minor into Macedonia and Greece.",
        [
            ("Derbe", "Acts 16:1"),
            ("Lystra", "Acts 16:1"),
            ("Troas", "Acts 16:8"),
            ("Neapolis", "Acts 16:11"),
            ("Philippi", "Acts 16:12"),
            ("Amphipolis", "Acts 17:1"),
            ("Apollonia", "Acts 17:1"),
            ("Thessalonica", "Acts 17:1"),
            ("Berea", "Acts 17:10"),
            ("Athens", "Acts 17:15"),
            ("Corinth", "Acts 18:1"),
            ("Ephesus", "Acts 18:19"),
            ("Caesarea", "Acts 18:22"),
        ],
    ),
    (
        "Paul's Third Missionary Journey",
        "Acts 18:23-21:16: through Asia Minor to Ephesus, then Macedonia, Greece, and back to Jerusalem.",
        [
            ("Ephesus", "Acts 19:1"),
            ("Troas", "Acts 20:6"),
            ("Assos", "Acts 20:13"),
            ("Mitylene", "Acts 20:14"),
            ("Chios", "Acts 20:15"),
            ("Samos", "Acts 20:15"),
            ("Miletus", "Acts 20:15"),
            ("Patara", "Acts 21:1"),
            ("Tyre", "Acts 21:3"),
            ("Caesarea", "Acts 21:8"),
            ("Jerusalem", "Acts 21:15"),
        ],
    ),
    (
        "Paul's Voyage to Rome",
        "Acts 27-28: the storm-driven voyage from Caesarea to Rome as a prisoner.",
        [
            ("Caesarea", "Acts 27:1"),
            ("Sidon", "Acts 27:3"),
            ("Cnidus", "Acts 27:7"),
            ("Fair Havens", "Acts 27:8"),
            ("Malta", "Acts 28:1"),
            ("Syracuse", "Acts 28:12"),
            ("Rhegium", "Acts 28:13"),
            ("Puteoli", "Acts 28:13"),
            ("Appii Forum", "Acts 28:15"),
            ("Rome", "Acts 28:16"),
        ],
    ),
]

# Known ambiguity: "Antioch" appears twice in journey 1 with the SAME name —
# Syrian Antioch (starting point) and Pisidian Antioch (a different city in
# what's now Turkey). Pleiades likely has separate entries for these under
# different titles ("Antiochia" variants) — the seed_map_locations.py curated
# list currently only captures one "Antioch" match. Flagged here rather than
# silently mapping both stops to the same coordinates, which would be wrong.
KNOWN_AMBIGUOUS_NAMES = {"Antioch"}


def run():
    locations_resp = supabase.table("map_locations").select("id, name").execute()
    name_to_location_id = {row["name"]: row["id"] for row in locations_resp.data}
    if not name_to_location_id:
        raise RuntimeError("map_locations is empty — run seed_map_locations.py first.")

    existing_journeys_resp = supabase.table("journeys").select("id, name").execute()
    existing_journey_names = {row["name"]: row["id"] for row in existing_journeys_resp.data}

    for journey_name, description, stops in JOURNEYS:
        if journey_name in existing_journey_names:
            journey_id = existing_journey_names[journey_name]
            print(f"'{journey_name}' already exists (id={journey_id}), reusing it")
        else:
            insert_resp = (
                supabase.table("journeys")
                .insert({"name": journey_name, "description": description, "source": "Acts 13-28"})
                .execute()
            )
            journey_id = insert_resp.data[0]["id"]
            print(f"Created journey '{journey_name}' (id={journey_id})")

        existing_stops_resp = (
            supabase.table("journey_stops").select("stop_order").eq("journey_id", journey_id).execute()
        )
        existing_orders = {r["stop_order"] for r in existing_stops_resp.data}

        stop_rows = []
        for order_idx, (place_name, verse_ref) in enumerate(stops, start=1):
            if order_idx in existing_orders:
                continue
            location_id = name_to_location_id.get(place_name)
            if not location_id:
                print(f"  SKIP stop {order_idx} '{place_name}' — no matching map_locations row "
                      f"(check seed_map_locations.py's BIBLICAL_PLACES list)")
                continue
            if place_name in KNOWN_AMBIGUOUS_NAMES:
                print(f"  NOTE stop {order_idx} '{place_name}' — ambiguous name, see "
                      f"KNOWN_AMBIGUOUS_NAMES comment; verify this points at the right site")
            stop_rows.append(
                {
                    "journey_id": journey_id,
                    "location_id": location_id,
                    "stop_order": order_idx,
                    "verse_reference": verse_ref,
                }
            )

        if stop_rows:
            supabase.table("journey_stops").insert(stop_rows).execute()
        print(f"  inserted {len(stop_rows)} stops for '{journey_name}'")

    print("Journey seeding complete.")


if __name__ == "__main__":
    run()
