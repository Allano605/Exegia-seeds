"""
Seed `cross_references` from the Treasury of Scripture Knowledge dataset via
scrollmapper/bible_databases.

VERIFIED SCHEMA (checked 2026-09-03, confirmed across multiple independent
mirrors' README tables, all describing the same real `cross_reference` MySQL
table): columns `id`, `from_book`, `from_chapter`, `from_verse`, `to_book`,
`to_chapter`, `to_verse` (start), `to_verse_end`, `votes`. `from_book`/`to_book`
are stored as full book name strings (e.g. "Genesis"), not numbers.

The file itself, `cross_references-mysql.sql`, is confirmed to exist at the
repo root by multiple independent forks' documentation. This script parses the
SQL INSERT statements directly with a regex rather than depending on an
unconfirmed CSV export path — the MySQL dump is the one file format I could
fully confirm exists, so it's the more solidly-grounded choice.

⚠️ The repo has both a `2024` (legacy, stable schema — matches the columns
above) and `2025`+ branch with "significant changes to the database schema"
per the repo's own README warning. This script targets the `2024` branch
deliberately, since that's the schema actually confirmed above. If you want
the newer schema, inspect it fresh before adapting this script.

License: CC BY — attribution to openbible.info required in-app. Underlying TSK
data itself is public domain.

Run: python seed_tsk_crossrefs.py
"""
import re
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert

SQL_URL = (
    "https://raw.githubusercontent.com/scrollmapper/bible_databases/2024/"
    "cross_references-mysql.sql"
)

# Matches: (id, 'From Book', from_chapter, from_verse, 'To Book', to_chapter, to_verse, to_verse_end, votes)
INSERT_ROW_RE = re.compile(
    r"\(\s*\d+\s*,\s*'([^']*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'([^']*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*\)"
)


def get_book_and_verse_maps():
    books_resp = supabase.table("books").select("id, name_en").execute()
    name_to_book_id = {row["name_en"]: row["id"] for row in books_resp.data}

    verse_map = {}
    start = 0
    page_size = 1000
    while True:
        resp = (
            supabase.table("verses")
            .select("id, book_id, chapter, verse")
            .range(start, start + page_size - 1)
            .execute()
        )
        if not resp.data:
            break
        for row in resp.data:
            verse_map[(row["book_id"], row["chapter"], row["verse"])] = row["id"]
        if len(resp.data) < page_size:
            break
        start += page_size

    return name_to_book_id, verse_map


def run():
    print("Loading book and verse maps...")
    name_to_book_id, verse_map = get_book_and_verse_maps()
    if not verse_map:
        raise RuntimeError("verses table is empty — run seed_kjv.py first.")
    print(f"  loaded {len(name_to_book_id)} books, {len(verse_map)} verses")

    print("Fetching TSK cross-references SQL dump (scrollmapper/bible_databases, 2024 branch)...")
    resp = requests.get(SQL_URL, timeout=120)
    resp.raise_for_status()
    sql_text = resp.text
    print(f"  downloaded {len(sql_text) / 1e6:.1f} MB")

    matches = INSERT_ROW_RE.findall(sql_text)
    print(f"  regex matched {len(matches)} candidate rows — "
          f"if this is 0, the dump's INSERT syntax doesn't match the expected "
          f"tuple shape and INSERT_ROW_RE needs adjusting against an actual "
          f"downloaded excerpt before trusting this run.")

    rows = []
    skipped = 0
    for from_book, from_ch, from_v, to_book, to_ch, to_v, to_v_end, votes in tqdm(matches, desc="Mapping"):
        from_book_id = name_to_book_id.get(from_book)
        to_book_id = name_to_book_id.get(to_book)
        from_id = verse_map.get((from_book_id, int(from_ch), int(from_v)))
        to_id = verse_map.get((to_book_id, int(to_ch), int(to_v)))
        if not from_id or not to_id:
            skipped += 1
            continue
        rows.append(
            {
                "from_verse_id": from_id,
                "to_verse_id": to_id,
                "source": "tsk",
                "relevance_rank": int(votes),
            }
        )

    print(f"  mapped {len(rows)} cross-references ({skipped} skipped — book/verse not matched)")
    batch_upsert("cross_references", rows, on_conflict="from_verse_id,to_verse_id,source")
    print("TSK cross-reference seeding complete.")


if __name__ == "__main__":
    run()
